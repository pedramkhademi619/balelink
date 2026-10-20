"""Test your bot with no network.

from balesdk import BaleClient
from balesdk.testing import FakeTransport

fake = FakeTransport(logged_in=True)
bale = BaleClient("test", transport=fake)
...
await fake.deliver("hello", chat_id=42)      # an incoming message
assert fake.sent[-1].text == "hi!"           # what your handler sent
"""

from __future__ import annotations

import itertools
import pathlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import BinaryIO, Dict, List, Optional, Union

from .errors import (
    CodeNotRequested,
    ConnectionFailed,
    NotLoggedIn,
    PasswordRequired,
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
from .transport import MessageCallback


@dataclass
class SentFile:
    chat: Chat
    file: FileSource
    kind: FileKind
    caption: Optional[str]


@dataclass
class FakeTransport:
    """An in-memory Bale. Script what it should do; read what was done."""

    logged_in: bool = False
    code: str = "12345"
    password: Optional[str] = None
    me_id: int = 1000
    fail_connect: bool = False
    users_by_phone: Dict[str, int] = field(default_factory=dict)

    # what happened
    sent: List[Message] = field(default_factory=list)
    sent_files: List[SentFile] = field(default_factory=list)
    edits: List[tuple] = field(default_factory=list)
    deleted: List[Message] = field(default_factory=list)
    reactions: List[tuple] = field(default_factory=list)
    seen: List[Chat] = field(default_factory=list)
    typing_log: List[tuple] = field(default_factory=list)
    codes_requested: List[str] = field(default_factory=list)
    history_store: Dict[int, List[Message]] = field(default_factory=dict)

    _connected: bool = False
    _on_message: Optional[MessageCallback] = None
    _pending_phone: Optional[str] = None
    _me: Optional[Me] = None
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    _error: Optional[str] = None

    # ---- state ------------------------------------------------------------------------

    @property
    def has_login(self) -> bool:
        return self.logged_in

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def me(self) -> Optional[Me]:
        return self._me

    def last_error(self) -> Optional[str]:
        return self._error

    def drop_connection(self) -> None:
        """Simulate losing the connection."""
        self._connected = False

    def restore_connection(self) -> None:
        self._connected = True

    # ---- signing in ----------------------------------------------------------------------

    async def request_code(self, phone: str) -> CodeRequest:
        self.codes_requested.append(phone)
        self._pending_phone = phone
        return CodeRequest(phone=phone, timeout_seconds=60)

    async def sign_in(self, code: str, password: Optional[str]) -> Me:
        if self._pending_phone is None:
            raise CodeNotRequested()
        if code != self.code:
            raise WrongCode()
        if self.password is not None:
            if not password:
                raise PasswordRequired()
            if password != self.password:
                raise WrongPassword()
        self.logged_in = True
        self._me = Me(id=self.me_id, phone=self._pending_phone)
        return self._me

    async def sign_out(self) -> None:
        self.logged_in = False
        self._connected = False
        self._me = None

    # ---- connection --------------------------------------------------------------------------

    async def start(self, on_message: MessageCallback) -> None:
        if not self.logged_in:
            raise NotLoggedIn()
        if self.fail_connect:
            self._error = "connect_failed"
            raise ConnectionFailed()
        self._on_message = on_message
        self._connected = True
        self._me = self._me or Me(id=self.me_id)

    async def stop(self) -> None:
        self._connected = False

    # ---- making and reading messages ---------------------------------------------------------------

    def _make(
        self,
        chat: Chat,
        text: Optional[str],
        sender_id: int,
        attachment: Optional[Attachment] = None,
    ) -> Message:
        return Message(
            id=next(self._ids),
            chat=chat,
            sender_id=sender_id,
            date=datetime.now(timezone.utc),
            text=text,
            attachment=attachment,
            from_me=sender_id == self.me_id,
        )

    async def deliver(
        self,
        text: Optional[str] = None,
        *,
        chat_id: int = 42,
        sender_id: Optional[int] = None,
        kind: ChatKind = ChatKind.PRIVATE,
        attachment: Optional[Attachment] = None,
    ) -> Message:
        """Pretend a message arrived (to a started client)."""
        assert self._on_message is not None, "start the client first"
        message = self._make(
            Chat(chat_id, kind), text, sender_id if sender_id is not None else chat_id, attachment
        )
        await self._on_message(message)
        return message

    # ---- the Transport methods -------------------------------------------------------------------------

    async def send_text(self, chat: Chat, text: str, reply_to: Optional[Message] = None) -> Message:
        self._need_connection()
        m = self._make(chat, text, self.me_id)
        m.raw = {"reply_to": reply_to.id if reply_to else None}
        self.sent.append(m)
        return m

    async def send_file(
        self,
        chat: Chat,
        file: FileSource,
        kind: FileKind,
        caption: Optional[str] = None,
        reply_to: Optional[Message] = None,
        file_name: Optional[str] = None,
    ) -> Message:
        self._need_connection()
        self.sent_files.append(SentFile(chat, file, kind, caption))
        m = self._make(
            chat,
            caption,
            self.me_id,
            Attachment(file_id=next(self._ids), access_hash=1, name=file_name),
        )
        self.sent.append(m)
        return m

    async def edit_text(self, message: Message, text: str) -> None:
        self._need_connection()
        self.edits.append((message.id, text))
        message.text = text

    async def delete_messages(self, messages: Sequence[Message], just_me: bool = False) -> None:
        self._need_connection()
        self.deleted.extend(messages)

    async def react(self, message: Message, emoji: str) -> None:
        self._need_connection()
        self.reactions.append((message.id, emoji))

    async def mark_seen(self, chat: Chat) -> None:
        self._need_connection()
        self.seen.append(chat)

    async def set_typing(self, chat: Chat, typing: bool) -> None:
        self._need_connection()
        self.typing_log.append((chat.id, typing))

    async def set_online(self, online: bool, timeout_seconds: int = 60) -> None:
        self._need_connection()

    async def history(
        self, chat: Chat, limit: int = 20, before: Optional[datetime] = None
    ) -> List[Message]:
        self._need_connection()
        found = list(reversed(self.history_store.get(chat.id, [])))
        if before is not None:
            found = [m for m in found if m.date < before]
        return found[:limit]

    async def download(
        self,
        attachment: Attachment,
        destination: Union[str, pathlib.Path, None] = None,
    ) -> Optional[BinaryIO]:
        self._need_connection()
        import io

        data = io.BytesIO(b"fake-bytes")
        if destination is not None:
            pathlib.Path(destination).write_bytes(data.getvalue())
            return None
        return data

    async def find_user_by_phone(self, phone: str) -> Optional[User]:
        self._need_connection()
        uid = self.users_by_phone.get(phone)
        return User(id=uid, name="Fake") if uid is not None else None

    async def get_user(self, chat: Chat) -> Optional[User]:
        self._need_connection()
        return User(id=chat.id, name=f"user {chat.id}")

    async def dialogs(self, limit: int = 40) -> List[Chat]:
        self._need_connection()
        return [Chat(i) for i in self.history_store][:limit]

    def _need_connection(self) -> None:
        if not self._connected:
            from .errors import NotConnected

            raise NotConnected()
