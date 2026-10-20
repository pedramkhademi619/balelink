"""Sessions of the gateway: each is one Bale account with an optional webhook."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..client import BaleClient
from ..errors import BaleError
from ..models import Message
from ..store import SessionStore
from .config import Settings
from .webhook import WebhookSender

log = logging.getLogger("balesdk.gateway")

ClientFactory = Callable[[str], BaleClient]
CACHE_SIZE = 500
STATE_FILE = "gateway.json"


class GatewayError(Exception):
    """A problem with the request itself (not with Bale)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def message_to_dict(m: Message) -> Dict[str, Any]:
    a = m.attachment
    return {
        "id": m.id,
        "chat": {"id": m.chat.id, "kind": m.chat.kind.value},
        "sender_id": m.sender_id,
        "from_me": m.from_me,
        "date": m.date.isoformat(),
        "timestamp": m.timestamp,
        "text": m.text,
        "attachment": None
        if a is None
        else {
            "file_id": a.file_id,
            "access_hash": a.access_hash,
            "name": a.name,
            "mime_type": a.mime_type,
            "size": a.size,
        },
    }


@dataclass
class Session:
    name: str
    client: BaleClient
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
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

    def describe(self) -> Dict[str, Any]:
        me = self.client.me
        return {
            "name": self.name,
            "status": self.status,
            "me": None if me is None else {"id": me.id, "phone": me.phone, "name": me.name},
            "webhook": {"url": self.webhook_url, "signed": bool(self.webhook_secret)}
            if self.webhook_url
            else None,
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
            session = self._make(name, cfg.get("webhook_url"), cfg.get("webhook_secret"))
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

    def _save_state(self) -> None:
        self.store.ensure_directory()
        data = {
            "sessions": {
                n: {"webhook_url": s.webhook_url, "webhook_secret": s.webhook_secret}
                for n, s in self.sessions.items()
            }
        }
        path = self._state_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), "utf-8")
        os.chmod(tmp, 0o600)  # it holds webhook secrets
        tmp.replace(path)

    # ---- sessions ---------------------------------------------------------------------------------

    def _make(self, name: str, url: Optional[str], secret: Optional[str]) -> Session:
        client = self._factory(name)
        session = Session(name, client, url, secret)
        client.on_message()(lambda m, s=session: self._incoming(s, m))
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
        self, name: str, webhook_url: Optional[str] = None, webhook_secret: Optional[str] = None
    ) -> Session:
        try:
            SessionStore.check_name(name)
        except ValueError as e:
            raise GatewayError(422, "INVALID_SESSION_NAME", str(e)) from e
        async with self._lock:
            if name in self.sessions:
                raise GatewayError(409, "SESSION_EXISTS", f"Session '{name}' already exists.")
            session = self._make(name, webhook_url, webhook_secret)
            self._save_state()
            return session

    async def delete(self, name: str) -> None:
        async with self._lock:
            session = self.get(name)
            if session.client.is_logged_in:
                try:
                    await session.client.logout()
                except BaleError:
                    log.warning("logout of %s failed; removing the saved login anyway", name)
                    await session.client.stop()
                    self.store.delete(name)
            else:
                await session.client.stop()
            del self.sessions[name]
            self._save_state()

    async def start(self, name: str) -> Session:
        session = self.get(name)
        await self._start(session, raise_errors=True)
        return session

    async def stop(self, name: str) -> Session:
        session = self.get(name)
        await session.client.stop()
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

    async def set_webhook(self, name: str, url: Optional[str], secret: Optional[str]) -> Session:
        session = self.get(name)
        session.webhook_url = url or None
        session.webhook_secret = (secret or None) if url else None
        self._save_state()
        return session

    # ---- login ------------------------------------------------------------------------------------------

    async def request_code(self, name: str, phone: str) -> Dict[str, Any]:
        session = self.get(name)
        req = await session.client.request_code(phone)
        session.code_sent = True
        return {"phone": req.phone, "timeout_seconds": req.timeout_seconds}

    async def verify(self, name: str, code: str, password: Optional[str]) -> Session:
        session = self.get(name)
        await session.client.sign_in(code, password=password)
        session.code_sent = False
        await self._start(session, raise_errors=True)
        return session

    # ---- events -------------------------------------------------------------------------------------------

    def _incoming(self, session: Session, message: Message) -> None:
        session.remember(message)
        if session.webhook_url:
            self.sender.send(
                session.webhook_url,
                session.webhook_secret,
                {"event": "message", "session": session.name, "message": message_to_dict(message)},
            )
