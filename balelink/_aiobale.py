"""The real transport: balelink on top of the ``aiobale`` library.

This is the only module that imports ``aiobale``. aiobale reverse-engineers
Bale's internal API (gRPC-Web over WebSocket, protobuf) and is MIT-licensed;
see NOTICE. Everything here translates between its types and balelink's.
"""

from __future__ import annotations

import asyncio
import io
import json
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
from .media import image_size, opus_duration_ms
from .models import (
    Attachment,
    Chat,
    ChatKind,
    CodeRequest,
    FileKind,
    FileSource,
    Group,
    Location,
    Me,
    Member,
    Message,
    User,
)
from .store import SessionStore
from .transport import EventCallback, MessageCallback

log = logging.getLogger("balelink.aiobale")


def _lib():
    """Import aiobale lazily, with a clear message if it is missing."""
    try:
        import aiobale  # noqa: F401
        from aiobale import enums as aio_enums
    except ImportError as e:  # pragma: no cover
        raise ImportError("balelink needs the 'aiobale-py' package: pip install aiobale-py") from e
    return aiobale, aio_enums


_KIND_BY_NAME = {
    "private": ChatKind.PRIVATE,
    "group": ChatKind.GROUP,
    "super_group": ChatKind.SUPER_GROUP,
    "supergroup": ChatKind.SUPER_GROUP,
    "channel": ChatKind.CHANNEL,
    "bot": ChatKind.BOT,
}


def _attachment_from(doc: Any) -> Attachment:
    """A DocumentMessage -> Attachment, with what Bale says the file is."""
    kind, width, height, duration = FileKind.DOCUMENT, None, None, None
    ext = getattr(doc, "ext", None)
    for attr, k in (
        ("photo", FileKind.PHOTO),
        ("voice", FileKind.VOICE),
        ("video", FileKind.VIDEO),
        ("gif", FileKind.GIF),
        ("audio", FileKind.AUDIO),
    ):
        part = getattr(ext, attr, None) if ext is not None else None
        if part is not None:
            kind = k
            width = getattr(part, "w", None)
            height = getattr(part, "h", None)
            duration = getattr(part, "duration", None)
            break
    caption = getattr(getattr(doc, "caption", None), "content", None)
    return Attachment(
        file_id=doc.file_id,
        access_hash=doc.access_hash,
        name=doc.name if isinstance(doc.name, str) else None,
        mime_type=doc.mime_type if isinstance(doc.mime_type, str) else None,
        size=doc.size,
        kind=kind,
        width=width,
        height=height,
        duration_ms=duration,
        caption=caption or None,
    )


def _document_from_extra(content: Any) -> Any:
    """Bale sometimes returns the file under a repeated key such as ``4-1``
    (seen on photos we sent ourselves); aiobale leaves it in the extras."""
    extra = getattr(content, "model_extra", None) or {}
    for key, value in extra.items():
        if key.startswith("4-") and isinstance(value, dict):
            try:
                from aiobale.types import DocumentMessage

                return DocumentMessage.model_validate(value)
            except Exception:
                log.debug("could not read the file under %s", key, exc_info=True)
    return None


# A location arrives as field 7 of the message content: a JSON string
#   {"dataType":"location","data":{"location":{"latitude":..,"longitude":..}}}
# aiobale has no type for it, so it sits in the content's extra fields.
def _location_from(content: Any) -> Optional[Location]:
    try:
        extra = getattr(content, "model_extra", None) or {}
        field = extra.get("7")
        raw = field.get("1") if isinstance(field, dict) else None
        if not isinstance(raw, str):
            return None
        data = json.loads(raw)
        if data.get("dataType") != "location":
            return None
        point = data["data"]["location"]
        return Location(float(point["latitude"]), float(point["longitude"]))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def location_payload(latitude: float, longitude: float) -> str:
    """The JSON string Bale's apps put in a location message."""
    return json.dumps(
        {
            "dataType": "location",
            "data": {"location": {"latitude": latitude, "longitude": longitude}},
        },
        separators=(",", ":"),
    )


def _read_all(file: Any) -> bytes:
    if isinstance(file, (str, pathlib.Path)):
        return pathlib.Path(file).read_bytes()
    if isinstance(file, (bytes, bytearray)):
        return bytes(file)
    return file.read()


def _name_of(data: bytes, kind: FileKind) -> str:
    if kind is FileKind.VOICE:
        return "voice.ogg"
    sig = data[:4]
    ext = (
        "png"
        if sig[:2] == b"\x89P"
        else "webp"
        if sig == b"RIFF"
        else "gif"
        if sig[:3] == b"GIF"
        else "jpg"
    )
    return f"photo.{ext}"


_KIND_BY_VALUE = {
    1: ChatKind.PRIVATE,
    2: ChatKind.GROUP,
    3: ChatKind.CHANNEL,
    4: ChatKind.BOT,
    5: ChatKind.SUPER_GROUP,
}


def kind_from_name(name: Any) -> ChatKind:
    """aiobale gives a chat type as an enum, its integer value, or its name."""
    raw = getattr(name, "value", name)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return _KIND_BY_VALUE.get(raw, ChatKind.UNKNOWN)
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
    """A :class:`~balelink.transport.Transport` backed by aiobale."""

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
        doc = m.document or _document_from_extra(m.content)
        attachment = _attachment_from(doc) if doc is not None else None
        my_id = self._me.id if self._me else None
        return Message(
            id=m.message_id,
            chat=Chat(m.chat.id, kind_from_name(m.chat.type)),
            sender_id=m.sender_id,
            date=Message.from_millis(m.date),
            text=m.text,
            attachment=attachment,
            from_me=my_id is not None and m.sender_id == my_id,
            location=_location_from(m.content),
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

    async def start(
        self, on_message: MessageCallback, on_event: Optional[EventCallback] = None
    ) -> None:
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

        if on_event is not None:

            async def emit(name: str, payload: dict) -> None:
                try:
                    await on_event(name, payload)
                except Exception:
                    log.exception("an event handler failed")

            @dispatcher.message_edited()
            async def _edited(update: Any) -> None:
                try:
                    message = self._to_message(update.message)
                except Exception:
                    log.debug("could not read an edited message", exc_info=True)
                    return
                await emit("message.edited", {"message": message})

            @dispatcher.message_deleted()
            async def _deleted(update: Any) -> None:
                peer = update.peer
                chat = Chat(peer.id, kind_from_name(peer.type))
                await emit("message.revoked", {"chat": chat, "ids": list(update.ids)})

        self._error = None
        client = self._new_client(dispatcher)
        self._client = client
        # Foreground mode reconnects by itself; run it as a task of ours.
        self._task = asyncio.create_task(
            client.start(signal_handling=False), name=f"balelink-{self._name}"
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

    async def send_location(
        self,
        chat: Chat,
        latitude: float,
        longitude: float,
        reply_to: Optional[Message] = None,
    ) -> Message:
        from aiobale.methods import SendMessage
        from aiobale.types import MessageContent
        from aiobale.utils import generate_id

        _, aio_enums = _lib()
        c = self._client_or_raise()
        peer_chat = c._build_chat(chat.id, _chat_type(aio_enums, chat.kind))
        message_id = generate_id()
        c._ignored_messages.targets.append(message_id)
        content = MessageContent(**{"7": {"1": location_payload(latitude, longitude)}})
        call = SendMessage(
            peer=c._resolve_peer(peer_chat),
            message_id=message_id,
            content=content,
            reply_to=c._ensure_info_message(reply_to.raw) if reply_to else None,
            chat=peer_chat,
        )
        result = await _call(c(call))
        return self._to_message(result.message)

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
        if kind in (FileKind.PHOTO, FileKind.VOICE):
            data = _read_all(file)
            file = io.BytesIO(data)
            file.name = file_name or getattr(file, "name", None) or _name_of(data, kind)
            kwargs[arg] = file
            if kind is FileKind.PHOTO:
                size = image_size(data)
                if size:
                    kwargs["cover_width"], kwargs["cover_height"] = size
            else:
                length = opus_duration_ms(data)
                if length:
                    kwargs["duration"] = length
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

    # ---- more message actions -------------------------------------------------------------

    @staticmethod
    def _ms(message: Message) -> int:
        return int(message.date.timestamp() * 1000)

    def _ctype(self, chat: Chat) -> Any:
        return _chat_type(_lib()[1], chat.kind)

    async def forward_messages(self, messages: Sequence[Message], to: Chat) -> None:
        c = self._client_or_raise()
        await _call(c.forward_messages([m.raw for m in messages], to.id, self._ctype(to)))

    async def pin_message(self, message: Message, just_me: bool = False) -> None:
        c = self._client_or_raise()
        await _call(
            c.pin_message(
                message.id, self._ms(message), message.chat.id, self._ctype(message.chat), just_me
            )
        )

    async def unpin_message(self, message: Message) -> None:
        c = self._client_or_raise()
        await _call(
            c.unpin_message(
                message.id, self._ms(message), message.chat.id, self._ctype(message.chat)
            )
        )

    async def unreact(self, message: Message, emoji: str) -> None:
        c = self._client_or_raise()
        await _call(
            c.remove_reaction(emoji, message.raw, message.chat.id, self._ctype(message.chat))
        )

    async def delete_chat(self, chat: Chat) -> None:
        await _call(self._client_or_raise().delete_chat(chat.id, self._ctype(chat)))

    async def clear_chat(self, chat: Chat) -> None:
        await _call(self._client_or_raise().clear_chat(chat.id, self._ctype(chat)))

    # ---- contacts ----------------------------------------------------------------------------------

    @staticmethod
    def _user_from(u: Any, *, is_contact: Optional[bool] = None) -> User:
        return User(
            id=u.id,
            name=getattr(u, "local_name", None) or getattr(u, "name", "") or "",
            username=getattr(u, "username", None),
            is_bot=bool(getattr(u, "is_bot", False)),
            is_contact=is_contact,
        )

    async def _users_of(self, peers: Any, *, is_contact: Optional[bool] = None) -> List[User]:
        c = self._client_or_raise()
        if not peers:
            return []
        try:
            found = await _call(c.load_users(list(peers)))
        except RequestFailed:
            # Names could not be loaded (e.g. a deleted account in the list);
            # the ids are still worth returning.
            return [User(id=p.id, name="", is_contact=is_contact) for p in peers]
        return [self._user_from(u, is_contact=is_contact) for u in found]

    async def contacts(self) -> List[User]:
        c = self._client_or_raise()
        return await self._users_of(await _call(c.load_contacts()), is_contact=True)

    async def add_contact(self, user_id: int) -> None:
        await _call(self._client_or_raise().add_contact(user_id))

    async def remove_contact(self, user_id: int) -> None:
        await _call(self._client_or_raise().remove_contact(user_id))

    async def rename_contact(self, user_id: int, name: str) -> None:
        await _call(self._client_or_raise().edit_user_local_name(name, user_id))

    async def block(self, user_id: int) -> None:
        await _call(self._client_or_raise().block_user(user_id))

    async def unblock(self, user_id: int) -> None:
        await _call(self._client_or_raise().unblock_user(user_id))

    async def blocked(self) -> List[User]:
        c = self._client_or_raise()
        return await self._users_of(await _call(c.load_blocked_users()))

    async def user_info(self, user_id: int) -> Optional[User]:
        _, aio_enums = _lib()
        c = self._client_or_raise()
        ptype = aio_enums.ChatType.PRIVATE
        base = await _call(c.load_user(user_id, ptype))
        if base is None:
            return None
        full = await _call(c.load_full_user(user_id, ptype))
        user = self._user_from(base)
        return User(
            id=user.id,
            name=user.name,
            username=user.username,
            is_bot=user.is_bot,
            about=getattr(full, "about", None),
            is_contact=bool(getattr(full, "is_contact", False)),
            is_blocked=bool(getattr(full, "is_blocked", False)),
        )

    # ---- groups -------------------------------------------------------------------------------------------

    @staticmethod
    def _group_from(g: Any, about: Optional[str] = None, link: Optional[str] = None) -> Group:
        return Group(
            id=g.id,
            title=getattr(g, "title", "") or "",
            about=about if about is not None else getattr(g, "about", None),
            members_count=getattr(g, "members_count", None),
            username=getattr(g, "username", None),
            owner_id=getattr(g, "owner_id", None),
            invite_link=link,
        )

    async def create_group(self, title: str, user_ids: Sequence[int]) -> Group:
        c = self._client_or_raise()
        r = await _call(c.create_group(title, users=tuple(user_ids)))
        return self._group_from(r.group, link=getattr(r, "invite_link", None))

    async def group_info(self, group_id: int) -> Group:
        c = self._client_or_raise()
        return self._group_from(await _call(c.get_full_group(group_id)))

    async def set_group_title(self, group_id: int, title: str) -> None:
        await _call(self._client_or_raise().edit_group_title(title, group_id))

    async def set_group_about(self, group_id: int, about: str) -> None:
        await _call(self._client_or_raise().edit_group_about(about, group_id))

    async def add_members(self, group_id: int, user_ids: Sequence[int]) -> None:
        await _call(self._client_or_raise().invite_users(group_id, list(user_ids)))

    async def remove_member(self, group_id: int, user_id: int) -> None:
        await _call(self._client_or_raise().kick_user(group_id, user_id))

    async def set_admin(self, group_id: int, user_id: int, admin: bool) -> None:
        c = self._client_or_raise()
        if admin:
            await _call(c.make_user_admin(group_id, user_id))
        else:
            await _call(c.remove_admin(group_id, user_id))

    async def leave_group(self, group_id: int) -> None:
        await _call(self._client_or_raise().leave_group(group_id))

    async def group_link(self, group_id: int, revoke: bool = False) -> str:
        c = self._client_or_raise()
        return str(
            await _call(c.revoke_group_link(group_id) if revoke else c.get_group_link(group_id))
        )

    async def join_group(self, link: str) -> Group:
        r = await _call(self._client_or_raise().join_chat(link))
        return self._group_from(r.group)

    async def members(self, group_id: int, limit: int = 100) -> List[Member]:
        found = await _call(self._client_or_raise().load_members(group_id, limit=limit))
        return [
            Member(user_id=m.id, name=getattr(m, "name", None), is_admin=bool(m.is_admin))
            for m in found
        ]

    # ---- my profile ---------------------------------------------------------------------------------------

    async def set_name(self, name: str) -> None:
        await _call(self._client_or_raise().edit_name(name))

    async def set_about(self, about: str) -> None:
        await _call(self._client_or_raise().edit_about(about))

    async def set_username(self, username: str) -> None:
        await _call(self._client_or_raise().edit_username(username))


async def _call(awaitable: Any) -> Any:
    """Run a library call, turning its failures into balelink's."""
    aiobale, _ = _lib()
    try:
        return await awaitable
    except aiobale.exceptions.AiobaleError as e:
        raise RequestFailed("Bale did not complete the request") from e
    except (OSError, asyncio.TimeoutError) as e:
        raise ConnectionFailed() from e
    except ValueError as e:  # pydantic.ValidationError is one: Bale sent a shape aiobale can't read
        raise RequestFailed("Bale's reply could not be read") from e


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
