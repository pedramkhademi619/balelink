"""The real transport: balesdk on top of the ``aiobale`` library.

This is the only module that imports ``aiobale``. aiobale reverse-engineers
Bale's internal API (gRPC-Web over WebSocket, protobuf) and is MIT-licensed;
see NOTICE. Everything here translates between its types and balesdk's.
"""

from __future__ import annotations

import asyncio
import io
import logging
import pathlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any, BinaryIO, List, Optional, Union

from .errors import (
    AuthError,
    CodeNotRequested,
    ConnectionFailed,
    InvalidPhone,
    NotLoggedIn,
    NotRegistered,
    NumberBanned,
    PasswordRequired,
    RateLimited,
    RequestFailed,
    WrongCode,
    WrongPassword,
)
from .models import (
    Attachment,
    Chat,
    ChatKind,
    CodeRequest,
    FileKind,
    FileSource,
    Me,
    Message,
    User,
)
from .store import SessionStore
from .transport import MessageCallback

log = logging.getLogger("balesdk.aiobale")


def _lib():
    """Import aiobale lazily, with a clear message if it is missing."""
    try:
        import aiobale  # noqa: F401
        from aiobale import enums as aio_enums
    except ImportError as e:  # pragma: no cover
        raise ImportError("balesdk needs the 'aiobale-py' package: pip install aiobale-py") from e
    return aiobale, aio_enums


_KIND_BY_NAME = {
    "private": ChatKind.PRIVATE,
    "group": ChatKind.GROUP,
    "super_group": ChatKind.SUPER_GROUP,
    "supergroup": ChatKind.SUPER_GROUP,
    "channel": ChatKind.CHANNEL,
    "bot": ChatKind.BOT,
}


def kind_from_name(name: Any) -> ChatKind:
    return _KIND_BY_NAME.get(str(getattr(name, "name", name)).lower(), ChatKind.UNKNOWN)


def _chat_type(aio_enums: Any, kind: ChatKind) -> Any:
    names = {
        ChatKind.PRIVATE: "PRIVATE",
        ChatKind.GROUP: "GROUP",
        ChatKind.SUPER_GROUP: "SUPER_GROUP",
        ChatKind.CHANNEL: "CHANNEL",
        ChatKind.BOT: "BOT",
    }
    return getattr(aio_enums.ChatType, names.get(kind, "PRIVATE"))


class AiobaleTransport:
    """A :class:`~balesdk.transport.Transport` backed by aiobale."""

    def __init__(self, name: str, store: SessionStore) -> None:
        self._name = store.check_name(name)
        self._store = store
        self._store.ensure_directory()
        self._path = store.path(name)

        self._auth_client: Any = None  # used only while signing in
        self._client: Any = None  # the live connection
        self._task: Optional[asyncio.Task[None]] = None
        self._transaction: Optional[str] = None
        self._phone: Optional[str] = None
        self._me: Optional[Me] = None
        self._error: Optional[str] = None

    # ---- helpers -------------------------------------------------------------------

    def _new_client(self, dispatcher: Any = None) -> Any:
        aiobale, _ = _lib()
        return aiobale.Client(
            dispatcher=dispatcher,
            session_file=self._path,
            show_update_errors=False,
        )

    def _client_or_raise(self) -> Any:
        if self._client is None or not self.is_connected:
            from .errors import NotConnected

            raise NotConnected()
        return self._client

    def _to_message(self, m: Any) -> Message:
        doc = m.document
        attachment = None
        if doc is not None:
            attachment = Attachment(
                file_id=doc.file_id,
                access_hash=doc.access_hash,
                name=doc.name if isinstance(doc.name, str) else None,
                mime_type=doc.mime_type if isinstance(doc.mime_type, str) else None,
                size=doc.size,
            )
        my_id = self._me.id if self._me else None
        return Message(
            id=m.message_id,
            chat=Chat(m.chat.id, kind_from_name(m.chat.type)),
            sender_id=m.sender_id,
            date=Message.from_millis(m.date),
            text=m.text,
            attachment=attachment,
            from_me=my_id is not None and m.sender_id == my_id,
            raw=m,
        )

    # ---- state -----------------------------------------------------------------------

    @property
    def has_login(self) -> bool:
        return self._store.exists(self._name)

    @property
    def is_connected(self) -> bool:
        try:
            return bool(self._client is not None and self._client.session.running)
        except Exception:
            return False

    @property
    def me(self) -> Optional[Me]:
        return self._me

    def last_error(self) -> Optional[str]:
        if self._task is not None and self._task.done() and not self._task.cancelled():
            if self._task.exception() is not None and self._error is None:
                self._error = "connection_lost"
        return self._error

    # ---- signing in --------------------------------------------------------------------

    async def request_code(self, phone: str) -> CodeRequest:
        aiobale, aio_enums = _lib()
        self._auth_client = self._auth_client or self._new_client()
        try:
            result = await self._auth_client.start_phone_auth(int(phone))
        except aiobale.exceptions.AiobaleError as e:
            raise RequestFailed("Bale did not accept the request") from e
        except Exception as e:
            raise ConnectionFailed() from e

        if isinstance(result, aio_enums.AuthErrors):
            raise _auth_error(aio_enums, result)

        self._transaction = result.transaction_hash
        self._phone = phone
        timeout = getattr(getattr(result, "code_timeout", None), "value", None)
        return CodeRequest(phone=phone, timeout_seconds=int(timeout) if timeout else None)

    async def sign_in(self, code: str, password: Optional[str]) -> Me:
        aiobale, aio_enums = _lib()
        if self._auth_client is None or self._transaction is None:
            raise CodeNotRequested()
        client, tx = self._auth_client, self._transaction

        try:
            result = await client.validate_code(code, tx)
            if result == aio_enums.AuthErrors.PASSWORD_NEEDED:
                if not password:
                    raise PasswordRequired()
                result = await client.validate_password(password, tx)
        except AuthError:
            raise
        except aiobale.exceptions.AiobaleError as e:
            raise RequestFailed("Bale did not accept the request") from e
        except Exception as e:
            raise ConnectionFailed() from e

        if isinstance(result, aio_enums.AuthErrors):
            raise _auth_error(aio_enums, result)

        self._store.secure(self._name)
        self._me = Me(id=int(client.id), phone=self._phone)
        self._transaction = None
        self._auth_client = None
        await self._close_quietly(client)  # else its HTTP session leaks
        return self._me

    @staticmethod
    async def _close_quietly(client: Any) -> None:
        try:
            await client.session.close()
        except Exception:
            log.debug("closing a client session raised", exc_info=True)

    async def sign_out(self) -> None:
        await self.stop()
        client = self._new_client()
        try:
            await client.sign_out(delete_session=True)
        except Exception:
            log.debug("sign-out request failed; deleting the local login anyway")
        self._store.delete(self._name)
        self._me = None

    # ---- connection -----------------------------------------------------------------------

    async def start(self, on_message: MessageCallback) -> None:
        aiobale, _ = _lib()
        if not self.has_login:
            raise NotLoggedIn()
        await self.stop()

        dispatcher = aiobale.Dispatcher()

        @dispatcher.message()
        async def _incoming(m: Any) -> None:
            try:
                await on_message(self._to_message(m))
            except Exception:
                log.exception("a message handler failed")

        self._error = None
        client = self._new_client(dispatcher)
        self._client = client
        # Foreground mode reconnects by itself; run it as a task of ours.
        self._task = asyncio.create_task(
            client.start(signal_handling=False), name=f"balesdk-{self._name}"
        )
        self._me = None

        deadline = asyncio.get_running_loop().time() + 20
        while asyncio.get_running_loop().time() < deadline:
            if self._task.done():
                exc = self._task.exception() if not self._task.cancelled() else None
                self._error = "connect_failed"
                raise ConnectionFailed() from exc
            if self.is_connected:
                break
            await asyncio.sleep(0.1)
        else:
            self._error = "connect_timeout"
            await self.stop()
            raise ConnectionFailed("Timed out connecting to Bale")

        ident = getattr(client, "id", None)
        if ident is not None:
            self._me = Me(id=int(ident), phone=self._phone)

    async def stop(self) -> None:
        client, task = self._client, self._task
        self._client = None
        self._task = None
        if client is not None:
            try:
                await client.stop()
            except Exception:
                log.debug("stopping the client raised", exc_info=True)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # ---- messages ----------------------------------------------------------------------------

    async def send_text(self, chat: Chat, text: str, reply_to: Optional[Message] = None) -> Message:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        sent = await _call(
            c.send_message(
                text,
                chat.id,
                _chat_type(aio_enums, chat.kind),
                reply_to=reply_to.raw if reply_to else None,
            )
        )
        if isinstance(sent, list):  # we never ask the library to split
            sent = sent[-1]
        return self._to_message(sent)

    async def send_file(
        self,
        chat: Chat,
        file: FileSource,
        kind: FileKind,
        caption: Optional[str] = None,
        reply_to: Optional[Message] = None,
        file_name: Optional[str] = None,
    ) -> Message:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        if isinstance(file, (bytes, bytearray)):
            buffer = io.BytesIO(bytes(file))
            buffer.name = file_name or "file"
            file = buffer
        ctype = _chat_type(aio_enums, chat.kind)
        quote = reply_to.raw if reply_to else None

        senders = {
            FileKind.DOCUMENT: ("send_document", "file"),
            FileKind.PHOTO: ("send_photo", "photo"),
            FileKind.VIDEO: ("send_video", "video"),
            FileKind.VOICE: ("send_voice", "voice"),
            FileKind.AUDIO: ("send_audio", "audio"),
            FileKind.GIF: ("send_gif", "gif"),
        }
        method, arg = senders[kind]
        kwargs = {arg: file, "chat_id": chat.id, "chat_type": ctype, "reply_to": quote}
        if caption is not None:
            kwargs["caption"] = caption
        sent = await _call(getattr(c, method)(**kwargs))
        return self._to_message(sent)

    async def edit_text(self, message: Message, text: str) -> None:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        await _call(
            c.edit_message(
                text, message.id, message.chat.id, _chat_type(aio_enums, message.chat.kind)
            )
        )

    async def delete_messages(self, messages: Sequence[Message], just_me: bool = False) -> None:
        if not messages:
            return
        _, aio_enums = _lib()
        c = self._client_or_raise()
        chat = messages[0].chat
        await _call(
            c.delete_messages(
                [m.id for m in messages],
                [int(m.date.timestamp() * 1000) for m in messages],
                chat.id,
                _chat_type(aio_enums, chat.kind),
                just_me=just_me,
            )
        )

    async def react(self, message: Message, emoji: str) -> None:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        await _call(
            c.set_reaction(
                emoji, message.raw, message.chat.id, _chat_type(aio_enums, message.chat.kind)
            )
        )

    async def mark_seen(self, chat: Chat) -> None:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        await _call(c.seen_chat(chat.id, _chat_type(aio_enums, chat.kind)))

    async def set_typing(self, chat: Chat, typing: bool) -> None:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        ctype = _chat_type(aio_enums, chat.kind)
        if typing:
            await _call(c.start_typing(chat.id, ctype))
        else:
            await _call(c.stop_typing(chat.id, ctype))

    async def set_online(self, online: bool, timeout_seconds: int = 60) -> None:
        c = self._client_or_raise()
        await _call(c.set_online(online, timeout_seconds))

    async def history(
        self, chat: Chat, limit: int = 20, before: Optional[datetime] = None
    ) -> List[Message]:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        # offset_date is in milliseconds; -1 means "from the newest".
        offset = int(before.timestamp() * 1000) if before is not None else -1
        found = await _call(
            c.load_history(
                chat.id, _chat_type(aio_enums, chat.kind), limit=limit, offset_date=offset
            )
        )
        return [self._to_message(m) for m in found]

    async def download(
        self,
        attachment: Attachment,
        destination: Union[str, pathlib.Path, None] = None,
    ) -> Optional[BinaryIO]:
        c = self._client_or_raise()
        return await _call(
            c.download_file(
                attachment.file_id,
                attachment.access_hash,
                pathlib.Path(destination) if destination else None,
            )
        )

    # ---- people and chats ------------------------------------------------------------------------

    async def find_user_by_phone(self, phone: str) -> Optional[User]:
        c = self._client_or_raise()
        peer = await _call(c.search_contact(phone))
        if peer is None:
            return None
        return User(id=peer.id, name="")

    async def get_user(self, chat: Chat) -> Optional[User]:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        u = await _call(c.load_user(chat.id, _chat_type(aio_enums, chat.kind)))
        if u is None:
            return None
        return User(
            id=u.id,
            name=u.local_name or u.name,
            username=u.username,
            is_bot=bool(u.is_bot),
        )

    async def dialogs(self, limit: int = 40) -> List[Chat]:
        c = self._client_or_raise()
        peers = await _call(c.load_dialogs(limit=limit))
        return [Chat(p.peer.id, kind_from_name(p.peer.type)) for p in peers]


# ---- shared bits ---------------------------------------------------------------------------------


async def _call(awaitable: Any) -> Any:
    """Run a library call, turning its failures into balesdk's."""
    aiobale, _ = _lib()
    try:
        return await awaitable
    except aiobale.exceptions.AiobaleError as e:
        raise RequestFailed("Bale did not complete the request") from e
    except (OSError, asyncio.TimeoutError) as e:
        raise ConnectionFailed() from e


def _auth_error(aio_enums: Any, failure: Any) -> AuthError:
    E = aio_enums.AuthErrors
    table = {
        E.NUMBER_BANNED: NumberBanned,
        E.AUTH_LIMIT: RateLimited,
        E.RATE_LIMIT: RateLimited,
        E.WRONG_CODE: WrongCode,
        E.PASSWORD_NEEDED: PasswordRequired,
        E.SIGN_UP_NEEDED: NotRegistered,
        E.WRONG_PASSWORD: WrongPassword,
        E.INVALID: InvalidPhone,
    }
    return table.get(failure, AuthError)()
