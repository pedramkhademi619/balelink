"""Sessions of the gateway: each is one Bale account with its webhooks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..client import BaleClient
from ..errors import BaleError
from ..models import Group, Member, Message, User
from ..store import SessionStore
from .config import Settings
from .webhook import WebhookSender

log = logging.getLogger("balelink.gateway")

ClientFactory = Callable[[str], BaleClient]
CACHE_SIZE = 500
STATE_FILE = "gateway.json"

# Events a webhook can subscribe to ("*" means all of them).
EVENTS = ("message", "message.any", "message.edited", "message.revoked", "session.status")


class GatewayError(Exception):
    """A problem with the request itself (not with Bale)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# ---- JSON shapes ----------------------------------------------------------------------


def message_to_dict(m: Message, media_url: Optional[str] = None) -> Dict[str, Any]:
    a = m.attachment
    loc = m.location
    return {
        "id": m.id,
        "chat": {"id": m.chat.id, "kind": m.chat.kind.value},
        "sender_id": m.sender_id,
        "from_me": m.from_me,
        "date": m.date.isoformat(),
        "timestamp": m.timestamp,
        "kind": m.kind,
        "text": m.text,
        "caption": m.caption,
        "has_media": a is not None,
        "media": None
        if a is None
        else {
            "kind": a.kind.value,
            "file_id": a.file_id,
            "access_hash": a.access_hash,
            "name": a.name,
            "mime_type": a.mime_type,
            "size": a.size,
            "width": a.width,
            "height": a.height,
            "duration_ms": a.duration_ms,
            "url": media_url,
        },
        "location": None
        if loc is None
        else {"latitude": loc.latitude, "longitude": loc.longitude, "maps_url": loc.maps_url},
    }


def user_to_dict(u: User) -> Dict[str, Any]:
    return {
        "id": u.id,
        "name": u.name,
        "username": u.username,
        "is_bot": u.is_bot,
        "about": u.about,
        "is_contact": u.is_contact,
        "is_blocked": u.is_blocked,
    }


def group_to_dict(g: Group) -> Dict[str, Any]:
    return {
        "id": g.id,
        "title": g.title,
        "about": g.about,
        "members_count": g.members_count,
        "username": g.username,
        "owner_id": g.owner_id,
        "invite_link": g.invite_link,
    }


def member_to_dict(m: Member) -> Dict[str, Any]:
    return {"user_id": m.user_id, "name": m.name, "is_admin": m.is_admin}


# ---- webhooks and sessions -----------------------------------------------------------------


@dataclass
class Webhook:
    url: str
    events: List[str] = field(default_factory=lambda: ["message"])
    secret: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    retries: Optional[int] = None

    def wants(self, event: str) -> bool:
        return "*" in self.events or event in self.events

    def describe(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "events": self.events,
            "signed": bool(self.secret),
            "headers": sorted(self.headers),  # names only - values may be secrets
            "retries": self.retries,
        }

    def to_state(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "events": self.events,
            "secret": self.secret,
            "headers": self.headers,
            "retries": self.retries,
        }

    @classmethod
    def from_state(cls, d: Dict[str, Any]) -> Webhook:
        return cls(
            url=d["url"],
            events=list(d.get("events") or ["message"]),
            secret=d.get("secret"),
            headers=dict(d.get("headers") or {}),
            retries=d.get("retries"),
        )


@dataclass
class Session:
    name: str
    client: BaleClient
    webhooks: List[Webhook] = field(default_factory=list)
    ignore_groups: bool = False
    ignore_private: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    code_sent: bool = False
    failure: Optional[str] = None
    cache: OrderedDict[int, Message] = field(default_factory=OrderedDict)

    @property
    def status(self) -> str:
        if self.client.is_connected:
            return "working"
        if self.client.is_logged_in:
            return "failed" if self.failure else "stopped"
        return "code_sent" if self.code_sent else "logged_out"

    def remember(self, m: Message) -> None:
        self.cache[m.id] = m
        while len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)

    def find(self, message_id: int) -> Message:
        m = self.cache.get(message_id)
        if m is None:
            raise GatewayError(
                404,
                "MESSAGE_NOT_FOUND",
                "That message is not among the recent ones this session saw.",
            )
        return m

    def ignores(self, m: Message) -> bool:
        return (self.ignore_groups and m.chat.is_group) or (
            self.ignore_private and m.chat.is_private
        )

    def describe(self) -> Dict[str, Any]:
        me = self.client.me
        return {
            "name": self.name,
            "status": self.status,
            "me": None if me is None else {"id": me.id, "phone": me.phone, "name": me.name},
            "webhook": self.webhooks[0].describe() if self.webhooks else None,
            "webhooks": [w.describe() for w in self.webhooks],
            "config": {
                "ignore": {"groups": self.ignore_groups, "private": self.ignore_private},
                "metadata": self.metadata,
            },
            "error": self.failure,
        }


class SessionManager:
    def __init__(
        self,
        settings: Settings,
        client_factory: Optional[ClientFactory] = None,
        sender: Optional[WebhookSender] = None,
    ) -> None:
        self.settings = settings
        self.store = SessionStore(settings.directory)
        self._factory = client_factory or (
            lambda name: BaleClient(name, directory=self.store.directory)
        )
        self.sender = sender or WebhookSender(settings.webhook_attempts, settings.webhook_timeout)
        self.sessions: Dict[str, Session] = {}
        self._lock_obj: Optional[asyncio.Lock] = None

    @property
    def _lock(self) -> asyncio.Lock:
        if self._lock_obj is None:  # made inside the running loop (see BaleClient)
            self._lock_obj = asyncio.Lock()
        return self._lock_obj

    # ---- lifecycle ---------------------------------------------------------------------

    async def startup(self) -> None:
        saved = self._load_state()
        names = set(saved) | set(self.store.names())
        for name in sorted(names):
            cfg = saved.get(name, {})
            session = self._make(name, cfg)
            if self.settings.autostart and session.client.is_logged_in:
                await self._start(session)

    async def shutdown(self) -> None:
        for s in list(self.sessions.values()):
            try:
                await s.client.stop()
            except Exception:
                log.exception("stopping %s", s.name)
        await self.sender.close()

    # ---- state file -----------------------------------------------------------------------

    def _state_path(self):
        return self.store.directory / STATE_FILE

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        try:
            return json.loads(self._state_path().read_text("utf-8")).get("sessions", {})
        except (OSError, ValueError):
            return {}

    def save_state(self) -> None:
        self.store.ensure_directory()
        data = {
            "sessions": {
                n: {
                    "webhooks": [w.to_state() for w in s.webhooks],
                    "ignore_groups": s.ignore_groups,
                    "ignore_private": s.ignore_private,
                    "metadata": s.metadata,
                }
                for n, s in self.sessions.items()
            }
        }
        path = self._state_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), "utf-8")
        os.chmod(tmp, 0o600)  # it holds webhook secrets
        tmp.replace(path)

    # ---- sessions ---------------------------------------------------------------------------------

    def _make(self, name: str, cfg: Optional[Dict[str, Any]] = None) -> Session:
        cfg = cfg or {}
        hooks = [Webhook.from_state(w) for w in cfg.get("webhooks", [])]
        if not hooks and cfg.get("webhook_url"):  # the first version's format
            hooks = [Webhook(cfg["webhook_url"], secret=cfg.get("webhook_secret"))]
        client = self._factory(name)
        session = Session(
            name,
            client,
            hooks,
            ignore_groups=bool(cfg.get("ignore_groups")),
            ignore_private=bool(cfg.get("ignore_private")),
            metadata=dict(cfg.get("metadata") or {}),
        )
        client.on_event(lambda event, payload, s=session: self._on_event(s, event, payload))
        self.sessions[name] = session
        return session

    def get(self, name: str) -> Session:
        s = self.sessions.get(name)
        if s is None:
            raise GatewayError(404, "SESSION_NOT_FOUND", f"No session named '{name}'.")
        return s

    def list(self) -> List[Session]:
        return list(self.sessions.values())

    async def create(
        self,
        name: str,
        webhooks: Optional[List[Webhook]] = None,
        ignore_groups: bool = False,
        ignore_private: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        try:
            SessionStore.check_name(name)
        except ValueError as e:
            raise GatewayError(422, "INVALID_SESSION_NAME", str(e)) from e
        async with self._lock:
            if name in self.sessions:
                raise GatewayError(409, "SESSION_EXISTS", f"Session '{name}' already exists.")
            session = self._make(
                name,
                {
                    "webhooks": [w.to_state() for w in webhooks or []],
                    "ignore_groups": ignore_groups,
                    "ignore_private": ignore_private,
                    "metadata": metadata or {},
                },
            )
            self.save_state()
            return session

    async def delete(self, name: str) -> None:
        async with self._lock:
            session = self.get(name)
            await self._logout(session)
            del self.sessions[name]
            self.save_state()

    async def _logout(self, session: Session) -> None:
        if session.client.is_logged_in:
            try:
                await session.client.logout()
            except BaleError:
                log.warning("logout of %s failed; removing the saved login anyway", session.name)
                await session.client.stop()
                self.store.delete(session.name)
        else:
            await session.client.stop()
        session.failure = None
        session.code_sent = False

    async def logout(self, name: str) -> Session:
        """Sign out of Bale but keep the session (and its webhooks) so it can log in again."""
        session = self.get(name)
        await self._logout(session)
        self._status_event(session)
        return session

    async def start(self, name: str) -> Session:
        session = self.get(name)
        await self._start(session, raise_errors=True)
        return session

    async def stop(self, name: str) -> Session:
        session = self.get(name)
        await session.client.stop()
        self._status_event(session)
        return session

    async def restart(self, name: str) -> Session:
        session = self.get(name)
        await session.client.stop()
        await self._start(session, raise_errors=True)
        return session

    async def _start(self, session: Session, raise_errors: bool = False) -> None:
        try:
            await session.client.start()
            session.failure = None
        except BaleError as e:
            session.failure = e.code
            log.warning("session %s did not start: %s", session.name, e.code)
            if raise_errors:
                raise
        finally:
            self._status_event(session)

    def set_webhooks(self, name: str, webhooks: List[Webhook]) -> Session:
        session = self.get(name)
        session.webhooks = webhooks
        self.save_state()
        return session

    def configure(
        self,
        name: str,
        ignore_groups: Optional[bool] = None,
        ignore_private: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        session = self.get(name)
        if ignore_groups is not None:
            session.ignore_groups = ignore_groups
        if ignore_private is not None:
            session.ignore_private = ignore_private
        if metadata is not None:
            session.metadata = metadata
        self.save_state()
        return session

    # ---- login ------------------------------------------------------------------------------------------

    async def request_code(self, name: str, phone: str) -> Dict[str, Any]:
        session = self.get(name)
        req = await session.client.request_code(phone)
        session.code_sent = True
        self._status_event(session)
        return {"phone": req.phone, "timeout_seconds": req.timeout_seconds}

    async def verify(self, name: str, code: str, password: Optional[str]) -> Session:
        session = self.get(name)
        await session.client.sign_in(code, password=password)
        session.code_sent = False
        await self._start(session, raise_errors=True)
        return session

    # ---- events -> webhooks ----------------------------------------------------------------------------------

    def media_url(self, session: Session, message: Message) -> Optional[str]:
        if message.attachment is None:
            return None
        base = (self.settings.public_url or "").rstrip("/")
        return f"{base}/sessions/{session.name}/messages/{message.id}/media"

    def _status_event(self, session: Session) -> None:
        self.dispatch(session, "session.status", {"status": session.status})

    def _on_event(self, session: Session, event: str, payload: Dict[str, Any]) -> None:
        if event in ("message", "message.any", "message.edited"):
            message: Message = payload["message"]
            session.remember(message)
            if session.ignores(message):
                return
            body: Dict[str, Any] = message_to_dict(message, self.media_url(session, message))
        elif event == "message.revoked":
            chat = payload["chat"]
            body = {"chat": {"id": chat.id, "kind": chat.kind.value}, "ids": payload["ids"]}
        elif event == "connection.up":
            event, body = "session.status", {"status": "working"}
        elif event == "connection.down":
            event, body = "session.status", {"status": "reconnecting"}
        else:
            return
        self.dispatch(session, event, body)

    def dispatch(self, session: Session, event: str, body: Dict[str, Any]) -> None:
        hooks = [w for w in session.webhooks if w.wants(event)]
        if not hooks:
            return
        me = session.client.me
        envelope = {
            "id": uuid.uuid4().hex,
            "timestamp": int(time.time() * 1000),
            "event": event,
            "session": session.name,
            "me": None if me is None else {"id": me.id, "phone": me.phone},
            "payload": body,
        }
        for w in hooks:
            self.sender.send(w.url, w.secret, envelope, w.headers, w.retries)
