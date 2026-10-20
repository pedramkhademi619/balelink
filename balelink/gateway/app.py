"""The FastAPI application."""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import mimetypes
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..errors import (
    AlreadyLoggedIn,
    BaleError,
    ChatNotFound,
    CodeNotRequested,
    ConnectionFailed,
    InvalidPhone,
    NotConnected,
    NotLoggedIn,
    NotRegistered,
    NumberBanned,
    PasswordRequired,
    RateLimited,
    RequestFailed,
    UnsupportedFile,
    WrongCode,
    WrongPassword,
)
from ..models import Chat, ChatKind, FileKind
from .config import Settings
from .manager import (
    EVENTS,
    ClientFactory,
    GatewayError,
    SessionManager,
    Webhook,
    group_to_dict,
    member_to_dict,
    message_to_dict,
    user_to_dict,
)
from .urlfetch import fetch
from .webhook import WebhookSender

log = logging.getLogger("balelink.gateway")

# How each library error is reported over HTTP. The body always carries the
# stable ``code`` - clients should branch on that, not on the status.
STATUS: Dict[type, int] = {
    InvalidPhone: 422,
    WrongCode: 400,
    PasswordRequired: 401,
    WrongPassword: 401,
    NumberBanned: 403,
    NotRegistered: 404,
    ChatNotFound: 404,
    RateLimited: 429,
    NotLoggedIn: 409,
    AlreadyLoggedIn: 409,
    CodeNotRequested: 409,
    NotConnected: 409,
    UnsupportedFile: 415,
    ConnectionFailed: 502,
    RequestFailed: 502,
}

MAX_FILE_BYTES = 50 * 1024 * 1024


# ---- request bodies ---------------------------------------------------------------------------


class WebhookIn(BaseModel):
    url: str
    events: List[str] = Field(["message"], description=f"Any of {', '.join(EVENTS)}, or '*'.")
    secret: Optional[str] = Field(None, description="Signs each request (HMAC-SHA256).")
    headers: Dict[str, str] = Field(default_factory=dict, description="Extra request headers.")
    retries: Optional[int] = Field(None, ge=1, le=10, description="Tries per event.")

    def build(self) -> Webhook:
        bad = [e for e in self.events if e != "*" and e not in EVENTS]
        if bad:
            raise GatewayError(422, "INVALID_EVENT", f"Unknown event(s): {', '.join(bad)}")
        return Webhook(self.url, self.events, self.secret, self.headers, self.retries)


class CreateSession(BaseModel):
    name: str
    webhook_url: Optional[str] = Field(None, description="Shortcut for one 'message' webhook.")
    webhook_secret: Optional[str] = None
    webhooks: List[WebhookIn] = Field(default_factory=list)
    ignore_groups: bool = False
    ignore_private: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WebhookBody(BaseModel):
    url: Optional[str] = Field(None, description="Where to POST events; null removes it.")
    secret: Optional[str] = None
    events: List[str] = ["message"]


class WebhooksBody(BaseModel):
    webhooks: List[WebhookIn]


class ConfigBody(BaseModel):
    ignore_groups: Optional[bool] = None
    ignore_private: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class CodeBody(BaseModel):
    phone: str


class VerifyBody(BaseModel):
    code: str
    password: Optional[str] = None


class To(BaseModel):
    to: str = Field(..., description="A phone number, or a chat id as digits with chat_id=true.")
    chat_id: bool = Field(False, description="Treat `to` as a chat id, not a phone number.")


class SendText(To):
    text: str
    reply_to: Optional[int] = Field(None, description="Id of a recent message to quote.")


class SendFile(To):
    data: Optional[str] = Field(None, description="The file, base64-encoded.")
    url: Optional[str] = Field(None, description="Or a public http(s) URL to fetch it from.")
    file_name: Optional[str] = None
    kind: Optional[FileKind] = Field(None, description="Guessed from the file when omitted.")
    caption: Optional[str] = None
    reply_to: Optional[int] = None


class SendLocation(To):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    reply_to: Optional[int] = None


class TypingBody(To):
    typing: bool = True


class ForwardBody(To):
    message_ids: List[int]


class PinBody(BaseModel):
    just_me: bool = False


class EditBody(BaseModel):
    text: str


class ReactBody(BaseModel):
    emoji: str


class UserRef(BaseModel):
    user: str = Field(..., description="Phone number, or a user id as digits.")


class NameBody(BaseModel):
    name: str


class GroupCreate(BaseModel):
    title: str
    members: List[str] = Field(default_factory=list, description="Phone numbers or user ids.")


class GroupUpdate(BaseModel):
    title: Optional[str] = None
    about: Optional[str] = None


class Members(BaseModel):
    members: List[str]


class Link(BaseModel):
    link: str


class ProfileBody(BaseModel):
    name: Optional[str] = None
    about: Optional[str] = None
    username: Optional[str] = None


def _target(to: str, chat_id: bool):
    if chat_id:
        if not to.lstrip("-").isdigit():
            raise GatewayError(422, "INVALID_CHAT_ID", "chat id must be digits")
        return int(to)
    return to


def _ref(value: str):
    """A phone number or a user id. Bale ids are at most 10 digits; a leading
    ``0`` or ``+``, or 11+ digits, means a phone number."""
    v = value.strip()
    if v.isdigit() and not v.startswith("0") and len(v) <= 10:
        return int(v)
    return v


def create_app(
    settings: Optional[Settings] = None,
    *,
    client_factory: Optional[ClientFactory] = None,
    sender: Optional[WebhookSender] = None,
) -> FastAPI:
    """Build the gateway. [client_factory] and [sender] exist for tests."""
    settings = settings or Settings.from_env()
    manager = SessionManager(settings, client_factory, sender)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.api_key:
            log.warning(
                "BALELINK_API_KEY is not set - anyone who can reach this port controls your accounts."
            )
        await manager.startup()
        yield
        await manager.shutdown()

    app = FastAPI(
        title="balelink gateway",
        version=__version__,
        description="Run Bale (بله) personal accounts as an HTTP service. Unofficial.",
        lifespan=lifespan,
    )
    app.state.manager = manager

    def error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)

    @app.exception_handler(GatewayError)
    async def _gateway_error(_: Request, e: GatewayError):
        return error(e.status, e.code, e.message)

    @app.exception_handler(BaleError)
    async def _bale_error(_: Request, e: BaleError):
        return error(STATUS.get(type(e), 400), e.code, e.message)

    async def authorize(x_api_key: Optional[str] = Header(None)) -> None:
        wanted = settings.api_key
        if wanted and not (x_api_key and hmac.compare_digest(x_api_key, wanted)):
            raise GatewayError(401, "UNAUTHORIZED", "Missing or wrong X-Api-Key.")

    auth = [Depends(authorize)]

    def client_of(name: str):
        return manager.get(name).client

    # ---- service ------------------------------------------------------------------------------

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/ping")
    async def ping() -> Dict[str, str]:
        return {"ping": "pong"}

    @app.get("/version", dependencies=auth)
    async def version() -> Dict[str, Any]:
        return {"version": __version__, "events": list(EVENTS)}

    # ---- sessions -------------------------------------------------------------------------------

    @app.get("/sessions", dependencies=auth)
    async def list_sessions() -> List[Dict[str, Any]]:
        return [s.describe() for s in manager.list()]

    @app.post("/sessions", status_code=201, dependencies=auth)
    async def create_session(body: CreateSession) -> Dict[str, Any]:
        hooks = [w.build() for w in body.webhooks]
        if body.webhook_url:
            hooks.insert(0, Webhook(body.webhook_url, ["message"], body.webhook_secret))
        s = await manager.create(
            body.name, hooks, body.ignore_groups, body.ignore_private, body.metadata
        )
        return s.describe()

    @app.get("/sessions/{name}", dependencies=auth)
    async def get_session(name: str) -> Dict[str, Any]:
        return manager.get(name).describe()

    @app.delete("/sessions/{name}", dependencies=auth)
    async def delete_session(name: str) -> Dict[str, Any]:
        await manager.delete(name)
        return {"deleted": name}

    @app.get("/sessions/{name}/me", dependencies=auth)
    async def me(name: str) -> Dict[str, Any]:
        s = manager.get(name)
        if s.client.me is None:
            raise GatewayError(409, "NOT_CONNECTED", "The session is not connected.")
        return s.describe()["me"]

    @app.put("/sessions/{name}/webhook", dependencies=auth)
    async def set_webhook(name: str, body: WebhookBody) -> Dict[str, Any]:
        hooks = (
            [WebhookIn(url=body.url, events=body.events, secret=body.secret).build()]
            if body.url
            else []
        )
        return manager.set_webhooks(name, hooks).describe()

    @app.put("/sessions/{name}/webhooks", dependencies=auth)
    async def set_webhooks(name: str, body: WebhooksBody) -> Dict[str, Any]:
        return manager.set_webhooks(name, [w.build() for w in body.webhooks]).describe()

    @app.put("/sessions/{name}/config", dependencies=auth)
    async def configure(name: str, body: ConfigBody) -> Dict[str, Any]:
        return manager.configure(
            name, body.ignore_groups, body.ignore_private, body.metadata
        ).describe()

    @app.post("/sessions/{name}/start", dependencies=auth)
    async def start_session(name: str) -> Dict[str, Any]:
        return (await manager.start(name)).describe()

    @app.post("/sessions/{name}/stop", dependencies=auth)
    async def stop_session(name: str) -> Dict[str, Any]:
        return (await manager.stop(name)).describe()

    @app.post("/sessions/{name}/restart", dependencies=auth)
    async def restart_session(name: str) -> Dict[str, Any]:
        return (await manager.restart(name)).describe()

    @app.post("/sessions/{name}/logout", dependencies=auth)
    async def logout_session(name: str) -> Dict[str, Any]:
        return (await manager.logout(name)).describe()

    # ---- login ----------------------------------------------------------------------------------------

    @app.post("/sessions/{name}/login/code", dependencies=auth)
    async def login_code(name: str, body: CodeBody) -> Dict[str, Any]:
        return await manager.request_code(name, body.phone)

    @app.post("/sessions/{name}/login/verify", dependencies=auth)
    async def login_verify(name: str, body: VerifyBody) -> Dict[str, Any]:
        return (await manager.verify(name, body.code, body.password)).describe()

    # ---- sending ------------------------------------------------------------------------------------------

    def remember(name: str, sent) -> Dict[str, Any]:
        s = manager.get(name)
        s.remember(sent)
        return message_to_dict(sent, manager.media_url(s, sent))

    @app.post("/sessions/{name}/messages", dependencies=auth)
    async def send_text(name: str, body: SendText) -> Dict[str, Any]:
        s = manager.get(name)
        reply = s.find(body.reply_to) if body.reply_to is not None else None
        sent = await s.client.send_text(_target(body.to, body.chat_id), body.text, reply_to=reply)
        return remember(name, sent)

    async def send_file_impl(name: str, body: SendFile, forced: Optional[FileKind]):
        s = manager.get(name)
        if (body.data is None) == (body.url is None):
            raise GatewayError(422, "INVALID_FILE_SOURCE", "Give exactly one of `data` or `url`.")
        file_name, mime = body.file_name, None
        if body.data is not None:
            try:
                raw = base64.b64decode(body.data, validate=True)
            except (binascii.Error, ValueError) as e:
                raise GatewayError(422, "INVALID_FILE_DATA", "`data` is not valid base64.") from e
        else:
            raw, mime, fetched_name = await fetch(body.url, settings.allow_private_urls)
            file_name = file_name or fetched_name
        if len(raw) > MAX_FILE_BYTES:
            raise GatewayError(413, "FILE_TOO_LARGE", "The file is over 50 MB.")
        mime = mime or (mimetypes.guess_type(file_name or "")[0] if file_name else None)
        kind = forced or body.kind or _guess_kind(mime)
        reply = s.find(body.reply_to) if body.reply_to is not None else None
        sent = await s.client.send_file(
            _target(body.to, body.chat_id),
            raw,
            kind=kind,
            caption=body.caption,
            reply_to=reply,
            file_name=file_name,
        )
        return remember(name, sent)

    def _guess_kind(mime: Optional[str]) -> FileKind:
        if not mime:
            return FileKind.DOCUMENT
        if mime == "image/gif":
            return FileKind.GIF
        if mime.startswith("image/"):
            return FileKind.PHOTO
        if mime.startswith("video/"):
            return FileKind.VIDEO
        if mime.startswith("audio/"):
            return FileKind.AUDIO
        return FileKind.DOCUMENT

    @app.post("/sessions/{name}/files", dependencies=auth)
    async def send_file(name: str, body: SendFile) -> Dict[str, Any]:
        return await send_file_impl(name, body, None)

    @app.post("/sessions/{name}/images", dependencies=auth)
    async def send_image(name: str, body: SendFile) -> Dict[str, Any]:
        return await send_file_impl(name, body, FileKind.PHOTO)

    @app.post("/sessions/{name}/voice", dependencies=auth)
    async def send_voice(name: str, body: SendFile) -> Dict[str, Any]:
        return await send_file_impl(name, body, FileKind.VOICE)

    @app.post("/sessions/{name}/videos", dependencies=auth)
    async def send_video(name: str, body: SendFile) -> Dict[str, Any]:
        return await send_file_impl(name, body, FileKind.VIDEO)

    @app.post("/sessions/{name}/location", dependencies=auth)
    async def send_location(name: str, body: SendLocation) -> Dict[str, Any]:
        s = manager.get(name)
        reply = s.find(body.reply_to) if body.reply_to is not None else None
        sent = await s.client.send_location(
            _target(body.to, body.chat_id), body.latitude, body.longitude, reply_to=reply
        )
        return remember(name, sent)

    @app.post("/sessions/{name}/typing", dependencies=auth)
    async def typing(name: str, body: TypingBody) -> Dict[str, Any]:
        c = client_of(name)
        chat = await c.resolve(_target(body.to, body.chat_id))
        await c._transport.set_typing(chat, body.typing)
        return {"typing": body.typing}

    @app.post("/sessions/{name}/forward", dependencies=auth)
    async def forward(name: str, body: ForwardBody) -> Dict[str, Any]:
        s = manager.get(name)
        messages = [s.find(i) for i in body.message_ids]
        await s.client.forward_messages(messages, _target(body.to, body.chat_id))
        return {"forwarded": body.message_ids}

    # ---- message actions ---------------------------------------------------------------------------------------

    @app.patch("/sessions/{name}/messages/{message_id}", dependencies=auth)
    async def edit_message(name: str, message_id: int, body: EditBody) -> Dict[str, Any]:
        s = manager.get(name)
        m = s.find(message_id)
        await s.client.edit_text(m, body.text)
        return message_to_dict(m, manager.media_url(s, m))

    @app.delete("/sessions/{name}/messages/{message_id}", dependencies=auth)
    async def delete_message(
        name: str, message_id: int, just_me: bool = Query(False)
    ) -> Dict[str, Any]:
        s = manager.get(name)
        await s.client.delete_messages([s.find(message_id)], just_me=just_me)
        s.cache.pop(message_id, None)
        return {"deleted": message_id}

    @app.post("/sessions/{name}/messages/{message_id}/reaction", dependencies=auth)
    async def react(name: str, message_id: int, body: ReactBody) -> Dict[str, Any]:
        s = manager.get(name)
        await s.client.react(s.find(message_id), body.emoji)
        return {"reacted": message_id, "emoji": body.emoji}

    @app.delete("/sessions/{name}/messages/{message_id}/reaction", dependencies=auth)
    async def unreact(name: str, message_id: int, emoji: str = Query(...)) -> Dict[str, Any]:
        s = manager.get(name)
        await s.client.unreact(s.find(message_id), emoji)
        return {"unreacted": message_id, "emoji": emoji}

    @app.post("/sessions/{name}/messages/{message_id}/pin", dependencies=auth)
    async def pin(name: str, message_id: int, body: Optional[PinBody] = None) -> Dict[str, Any]:
        s = manager.get(name)
        await s.client.pin_message(s.find(message_id), just_me=bool(body and body.just_me))
        return {"pinned": message_id}

    @app.delete("/sessions/{name}/messages/{message_id}/pin", dependencies=auth)
    async def unpin(name: str, message_id: int) -> Dict[str, Any]:
        s = manager.get(name)
        await s.client.unpin_message(s.find(message_id))
        return {"unpinned": message_id}

    @app.get("/sessions/{name}/messages/{message_id}/media", dependencies=auth)
    async def media(name: str, message_id: int) -> Response:
        s = manager.get(name)
        m = s.find(message_id)
        if m.attachment is None:
            raise GatewayError(404, "NO_MEDIA", "That message has no file.")
        stream = await s.client.download(m.attachment)
        data = stream.read() if stream is not None else b""
        a = m.attachment
        headers = {
            "Content-Disposition": f'inline; filename="{(a.name or "file").replace(chr(34), "")}"'
        }
        return Response(data, media_type=a.mime_type or "application/octet-stream", headers=headers)

    # ---- chats ------------------------------------------------------------------------------------------------------

    @app.post("/sessions/{name}/chats/{chat_id}/seen", dependencies=auth)
    async def seen(name: str, chat_id: int) -> Dict[str, Any]:
        await client_of(name).mark_seen(chat_id)
        return {"seen": chat_id}

    @app.get("/sessions/{name}/chats/{chat_id}/messages", dependencies=auth)
    async def history(
        name: str,
        chat_id: int,
        limit: int = Query(20, ge=1, le=200),
        before: Optional[int] = Query(
            None, description="Only older than this timestamp (seconds)."
        ),
    ) -> List[Dict[str, Any]]:
        from datetime import datetime, timezone

        s = manager.get(name)
        when = datetime.fromtimestamp(before, tz=timezone.utc) if before is not None else None
        found = await s.client.history(chat_id, limit, before=when)
        for m in found:
            s.remember(m)
        return [message_to_dict(m, manager.media_url(s, m)) for m in found]

    @app.get("/sessions/{name}/chats", dependencies=auth)
    async def chats(name: str, limit: int = Query(40, ge=1, le=200)) -> List[Dict[str, Any]]:
        found = await client_of(name).dialogs(limit)
        return [{"id": c.id, "kind": c.kind.value} for c in found]

    @app.delete("/sessions/{name}/chats/{chat_id}", dependencies=auth)
    async def delete_chat(name: str, chat_id: int) -> Dict[str, Any]:
        await client_of(name).delete_chat(chat_id)
        return {"deleted": chat_id}

    @app.post("/sessions/{name}/chats/{chat_id}/clear", dependencies=auth)
    async def clear_chat(name: str, chat_id: int) -> Dict[str, Any]:
        await client_of(name).clear_chat(chat_id)
        return {"cleared": chat_id}

    # ---- contacts ------------------------------------------------------------------------------------------------------

    @app.get("/sessions/{name}/contacts", dependencies=auth)
    async def contacts(name: str) -> List[Dict[str, Any]]:
        return [user_to_dict(u) for u in await client_of(name).contacts()]

    @app.get("/sessions/{name}/contacts/check-exists", dependencies=auth)
    async def check_exists(name: str, phone: str = Query(...)) -> Dict[str, Any]:
        found = await client_of(name).check_phone(phone)
        return {"exists": found is not None, "user_id": found.id if found else None}

    @app.get("/sessions/{name}/contacts/blocked", dependencies=auth)
    async def blocked(name: str) -> List[Dict[str, Any]]:
        return [user_to_dict(u) for u in await client_of(name).blocked()]

    @app.get("/sessions/{name}/contacts/{user_id}", dependencies=auth)
    async def contact(name: str, user_id: int) -> Dict[str, Any]:
        info = await client_of(name).user_info(user_id)
        if info is None:
            raise GatewayError(404, "CHAT_NOT_FOUND", "No such user.")
        return user_to_dict(info)

    @app.post("/sessions/{name}/contacts", dependencies=auth)
    async def add_contact(name: str, body: UserRef) -> Dict[str, Any]:
        await client_of(name).add_contact(_ref(body.user))
        return {"added": body.user}

    @app.delete("/sessions/{name}/contacts/{user_id}", dependencies=auth)
    async def remove_contact(name: str, user_id: int) -> Dict[str, Any]:
        await client_of(name).remove_contact(user_id)
        return {"removed": user_id}

    @app.put("/sessions/{name}/contacts/{user_id}", dependencies=auth)
    async def rename_contact(name: str, user_id: int, body: NameBody) -> Dict[str, Any]:
        await client_of(name).rename_contact(user_id, body.name)
        return {"renamed": user_id, "name": body.name}

    @app.post("/sessions/{name}/contacts/{user_id}/block", dependencies=auth)
    async def block(name: str, user_id: int) -> Dict[str, Any]:
        await client_of(name).block(user_id)
        return {"blocked": user_id}

    @app.post("/sessions/{name}/contacts/{user_id}/unblock", dependencies=auth)
    async def unblock(name: str, user_id: int) -> Dict[str, Any]:
        await client_of(name).unblock(user_id)
        return {"unblocked": user_id}

    # ---- groups ------------------------------------------------------------------------------------------------------------

    @app.post("/sessions/{name}/groups", status_code=201, dependencies=auth)
    async def create_group(name: str, body: GroupCreate) -> Dict[str, Any]:
        g = await client_of(name).create_group(body.title, [_ref(m) for m in body.members])
        return group_to_dict(g)

    @app.post("/sessions/{name}/groups/join", dependencies=auth)
    async def join_group(name: str, body: Link) -> Dict[str, Any]:
        return group_to_dict(await client_of(name).join_group(body.link))

    @app.get("/sessions/{name}/groups/{group_id}", dependencies=auth)
    async def group_info(name: str, group_id: int) -> Dict[str, Any]:
        return group_to_dict(await client_of(name).group_info(group_id))

    @app.put("/sessions/{name}/groups/{group_id}", dependencies=auth)
    async def update_group(name: str, group_id: int, body: GroupUpdate) -> Dict[str, Any]:
        c = client_of(name)
        if body.title is not None:
            await c.set_group_title(group_id, body.title)
        if body.about is not None:
            await c.set_group_about(group_id, body.about)
        return group_to_dict(await c.group_info(group_id))

    @app.post("/sessions/{name}/groups/{group_id}/leave", dependencies=auth)
    async def leave_group(name: str, group_id: int) -> Dict[str, Any]:
        await client_of(name).leave_group(group_id)
        return {"left": group_id}

    @app.get("/sessions/{name}/groups/{group_id}/members", dependencies=auth)
    async def members(
        name: str, group_id: int, limit: int = Query(100, ge=1, le=1000)
    ) -> List[Dict[str, Any]]:
        return [member_to_dict(m) for m in await client_of(name).members(group_id, limit)]

    @app.post("/sessions/{name}/groups/{group_id}/members", dependencies=auth)
    async def add_members(name: str, group_id: int, body: Members) -> Dict[str, Any]:
        await client_of(name).add_members(group_id, [_ref(m) for m in body.members])
        return {"added": body.members}

    @app.delete("/sessions/{name}/groups/{group_id}/members/{user_id}", dependencies=auth)
    async def remove_member(name: str, group_id: int, user_id: int) -> Dict[str, Any]:
        await client_of(name).remove_member(group_id, user_id)
        return {"removed": user_id}

    @app.post("/sessions/{name}/groups/{group_id}/admins/{user_id}", dependencies=auth)
    async def make_admin(name: str, group_id: int, user_id: int) -> Dict[str, Any]:
        await client_of(name).set_admin(group_id, user_id, True)
        return {"admin": user_id}

    @app.delete("/sessions/{name}/groups/{group_id}/admins/{user_id}", dependencies=auth)
    async def remove_admin(name: str, group_id: int, user_id: int) -> Dict[str, Any]:
        await client_of(name).set_admin(group_id, user_id, False)
        return {"admin_removed": user_id}

    @app.get("/sessions/{name}/groups/{group_id}/invite-link", dependencies=auth)
    async def invite_link(name: str, group_id: int) -> Dict[str, Any]:
        return {"link": await client_of(name).group_link(group_id)}

    @app.post("/sessions/{name}/groups/{group_id}/invite-link/revoke", dependencies=auth)
    async def revoke_invite_link(name: str, group_id: int) -> Dict[str, Any]:
        return {"link": await client_of(name).group_link(group_id, revoke=True)}

    # ---- profile -------------------------------------------------------------------------------------------------------------

    @app.put("/sessions/{name}/profile", dependencies=auth)
    async def profile(name: str, body: ProfileBody) -> Dict[str, Any]:
        c = client_of(name)
        if body.name is not None:
            await c.set_name(body.name)
        if body.about is not None:
            await c.set_about(body.about)
        if body.username is not None:
            await c.set_username(body.username)
        return {"updated": [k for k, v in body.model_dump().items() if v is not None]}

    return app


__all__ = ["create_app", "Chat", "ChatKind"]
