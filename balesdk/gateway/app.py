"""The FastAPI application."""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, Query, Request
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
from ..models import FileKind
from .config import Settings
from .manager import ClientFactory, GatewayError, SessionManager, message_to_dict
from .webhook import WebhookSender

log = logging.getLogger("balesdk.gateway")

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


class CreateSession(BaseModel):
    name: str
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None


class WebhookBody(BaseModel):
    url: Optional[str] = Field(None, description="Where to POST events; null removes it.")
    secret: Optional[str] = Field(None, description="Signs each request (HMAC-SHA256).")


class CodeBody(BaseModel):
    phone: str


class VerifyBody(BaseModel):
    code: str
    password: Optional[str] = None


class SendText(BaseModel):
    to: str = Field(..., description="A phone number, or a chat id as digits with chat_id=true.")
    text: str
    reply_to: Optional[int] = Field(None, description="Id of a recent message to quote.")
    chat_id: bool = Field(False, description="Treat `to` as a chat id, not a phone number.")


class SendFile(BaseModel):
    to: str
    data: str = Field(..., description="The file, base64-encoded.")
    file_name: Optional[str] = None
    kind: FileKind = FileKind.DOCUMENT
    caption: Optional[str] = None
    reply_to: Optional[int] = None
    chat_id: bool = False


class EditBody(BaseModel):
    text: str


class ReactBody(BaseModel):
    emoji: str


def _target(to: str, chat_id: bool):
    if chat_id:
        if not to.lstrip("-").isdigit():
            raise GatewayError(422, "INVALID_CHAT_ID", "chat id must be digits")
        return int(to)
    return to


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
                "BALESDK_API_KEY is not set - anyone who can reach this port controls your accounts."
            )
        await manager.startup()
        yield
        await manager.shutdown()

    app = FastAPI(
        title="balesdk gateway",
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

    # ---- service ------------------------------------------------------------------------------

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "version": __version__}

    # ---- sessions -------------------------------------------------------------------------------

    @app.get("/sessions", dependencies=auth)
    async def list_sessions() -> List[Dict[str, Any]]:
        return [s.describe() for s in manager.list()]

    @app.post("/sessions", status_code=201, dependencies=auth)
    async def create_session(body: CreateSession) -> Dict[str, Any]:
        s = await manager.create(body.name, body.webhook_url, body.webhook_secret)
        return s.describe()

    @app.get("/sessions/{name}", dependencies=auth)
    async def get_session(name: str) -> Dict[str, Any]:
        return manager.get(name).describe()

    @app.delete("/sessions/{name}", dependencies=auth)
    async def delete_session(name: str) -> Dict[str, Any]:
        await manager.delete(name)
        return {"deleted": name}

    @app.put("/sessions/{name}/webhook", dependencies=auth)
    async def set_webhook(name: str, body: WebhookBody) -> Dict[str, Any]:
        return (await manager.set_webhook(name, body.url, body.secret)).describe()

    @app.post("/sessions/{name}/start", dependencies=auth)
    async def start_session(name: str) -> Dict[str, Any]:
        return (await manager.start(name)).describe()

    @app.post("/sessions/{name}/stop", dependencies=auth)
    async def stop_session(name: str) -> Dict[str, Any]:
        return (await manager.stop(name)).describe()

    # ---- login ----------------------------------------------------------------------------------------

    @app.post("/sessions/{name}/login/code", dependencies=auth)
    async def login_code(name: str, body: CodeBody) -> Dict[str, Any]:
        return await manager.request_code(name, body.phone)

    @app.post("/sessions/{name}/login/verify", dependencies=auth)
    async def login_verify(name: str, body: VerifyBody) -> Dict[str, Any]:
        return (await manager.verify(name, body.code, body.password)).describe()

    # ---- messages ------------------------------------------------------------------------------------------

    @app.post("/sessions/{name}/messages", dependencies=auth)
    async def send_text(name: str, body: SendText) -> Dict[str, Any]:
        s = manager.get(name)
        reply = s.find(body.reply_to) if body.reply_to is not None else None
        sent = await s.client.send_text(_target(body.to, body.chat_id), body.text, reply_to=reply)
        s.remember(sent)
        return message_to_dict(sent)

    @app.post("/sessions/{name}/files", dependencies=auth)
    async def send_file(name: str, body: SendFile) -> Dict[str, Any]:
        s = manager.get(name)
        try:
            data = base64.b64decode(body.data, validate=True)
        except (binascii.Error, ValueError) as e:
            raise GatewayError(422, "INVALID_FILE_DATA", "`data` is not valid base64.") from e
        if len(data) > MAX_FILE_BYTES:
            raise GatewayError(413, "FILE_TOO_LARGE", "The file is over 50 MB.")
        reply = s.find(body.reply_to) if body.reply_to is not None else None
        sent = await s.client.send_file(
            _target(body.to, body.chat_id),
            data,
            kind=body.kind,
            caption=body.caption,
            reply_to=reply,
            file_name=body.file_name,
        )
        s.remember(sent)
        return message_to_dict(sent)

    @app.patch("/sessions/{name}/messages/{message_id}", dependencies=auth)
    async def edit_message(name: str, message_id: int, body: EditBody) -> Dict[str, Any]:
        s = manager.get(name)
        m = s.find(message_id)
        await s.client.edit_text(m, body.text)
        return message_to_dict(m)

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

    @app.post("/sessions/{name}/chats/{chat_id}/seen", dependencies=auth)
    async def seen(name: str, chat_id: int) -> Dict[str, Any]:
        await manager.get(name).client.mark_seen(chat_id)
        return {"seen": chat_id}

    @app.get("/sessions/{name}/chats/{chat_id}/messages", dependencies=auth)
    async def history(
        name: str, chat_id: int, limit: int = Query(20, ge=1, le=200)
    ) -> List[Dict[str, Any]]:
        s = manager.get(name)
        found = await s.client.history(chat_id, limit)
        for m in found:
            s.remember(m)
        return [message_to_dict(m) for m in found]

    @app.get("/sessions/{name}/chats", dependencies=auth)
    async def chats(name: str, limit: int = Query(40, ge=1, le=200)) -> List[Dict[str, Any]]:
        found = await manager.get(name).client.dialogs(limit)
        return [{"id": c.id, "kind": c.kind.value} for c in found]

    return app
