"""Test your bot with no network.

from balelink import BaleClient
from balelink.testing import FakeTransport

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
    Group,
    Location,
    Me,
    Member,
    Message,
    User,
)
from .transport import EventCallback, MessageCallback


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
    forwarded: List[tuple] = field(default_factory=list)
    pinned: List[tuple] = field(default_factory=list)
    contact_list: Dict[int, User] = field(default_factory=dict)
    blocked_ids: set = field(default_factory=set)
    groups: Dict[int, Group] = field(default_factory=dict)
    group_members: Dict[int, Dict[int, Member]] = field(default_factory=dict)
    profile: Dict[str, str] = field(default_factory=dict)
    cleared: List[int] = field(default_factory=list)
    chats_deleted: List[int] = field(default_factory=list)

    _connected: bool = False
    _on_message: Optional[MessageCallback] = None
    _on_event: Optional[EventCallback] = None
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

    async def start(
        self, on_message: MessageCallback, on_event: Optional[EventCallback] = None
    ) -> None:
        if not self.logged_in:
            raise NotLoggedIn()
        if self.fail_connect:
            self._error = "connect_failed"
            raise ConnectionFailed()
        self._on_message = on_message
        self._on_event = on_event
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
        location: Optional[Location] = None,
    ) -> Message:
        """Pretend a message arrived (to a started client)."""
        assert self._on_message is not None, "start the client first"
        message = self._make(
            Chat(chat_id, kind), text, sender_id if sender_id is not None else chat_id, attachment
        )
        message.location = location
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

    async def send_location(
        self,
        chat: Chat,
        latitude: float,
        longitude: float,
        reply_to: Optional[Message] = None,
    ) -> Message:
        self._need_connection()
        m = self._make(chat, None, self.me_id)
        m.location = Location(latitude, longitude)
        m.raw = {"reply_to": reply_to.id if reply_to else None}
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

    # ---- events you can trigger in tests ---------------------------------------------------------

    async def deliver_edit(self, message: Message, text: str) -> None:
        """Pretend someone edited [message]."""
        assert self._on_event is not None, "start the client first"
        message.text = text
        await self._on_event("message.edited", {"message": message})

    async def deliver_revoke(self, chat_id: int, ids: Sequence[int]) -> None:
        """Pretend messages were deleted."""
        assert self._on_event is not None, "start the client first"
        await self._on_event("message.revoked", {"chat": Chat(chat_id), "ids": list(ids)})

    # ---- more message actions --------------------------------------------------------------------

    async def forward_messages(self, messages: Sequence[Message], to: Chat) -> None:
        self._need_connection()
        self.forwarded.append((to.id, [m.id for m in messages]))

    async def pin_message(self, message: Message, just_me: bool = False) -> None:
        self._need_connection()
        self.pinned.append((message.id, True, just_me))

    async def unpin_message(self, message: Message) -> None:
        self._need_connection()
        self.pinned.append((message.id, False, False))

    async def unreact(self, message: Message, emoji: str) -> None:
        self._need_connection()
        self.reactions.append((message.id, None))

    async def delete_chat(self, chat: Chat) -> None:
        self._need_connection()
        self.chats_deleted.append(chat.id)

    async def clear_chat(self, chat: Chat) -> None:
        self._need_connection()
        self.cleared.append(chat.id)

    # ---- contacts -------------------------------------------------------------------------------------

    async def contacts(self) -> List[User]:
        self._need_connection()
        return list(self.contact_list.values())

    async def add_contact(self, user_id: int) -> None:
        self._need_connection()
        self.contact_list[user_id] = User(id=user_id, name=f"user {user_id}", is_contact=True)

    async def remove_contact(self, user_id: int) -> None:
        self._need_connection()
        self.contact_list.pop(user_id, None)

    async def rename_contact(self, user_id: int, name: str) -> None:
        self._need_connection()
        self.contact_list[user_id] = User(id=user_id, name=name, is_contact=True)

    async def block(self, user_id: int) -> None:
        self._need_connection()
        self.blocked_ids.add(user_id)

    async def unblock(self, user_id: int) -> None:
        self._need_connection()
        self.blocked_ids.discard(user_id)

    async def blocked(self) -> List[User]:
        self._need_connection()
        return [User(id=i, name=f"user {i}") for i in sorted(self.blocked_ids)]

    async def user_info(self, user_id: int) -> Optional[User]:
        self._need_connection()
        known = self.contact_list.get(user_id)
        return User(
            id=user_id,
            name=known.name if known else f"user {user_id}",
            about="about text",
            is_contact=known is not None,
            is_blocked=user_id in self.blocked_ids,
        )

    # ---- groups ----------------------------------------------------------------------------------------

    async def create_group(self, title: str, user_ids: Sequence[int]) -> Group:
        self._need_connection()
        gid = 9000 + len(self.groups)
        g = Group(
            id=gid,
            title=title,
            members_count=len(user_ids) + 1,
            invite_link=f"https://ble.ir/join/{gid}",
        )
        self.groups[gid] = g
        self.group_members[gid] = {self.me_id: Member(self.me_id, "me", True)}
        for u in user_ids:
            self.group_members[gid][u] = Member(u, f"user {u}", False)
        return g

    def _group(self, group_id: int) -> Group:
        from .errors import ChatNotFound

        if group_id not in self.groups:
            raise ChatNotFound()
        return self.groups[group_id]

    def _refresh(self, group_id: int, **changes) -> None:
        import dataclasses

        g = self._group(group_id)
        changes.setdefault("members_count", len(self.group_members[group_id]))
        self.groups[group_id] = dataclasses.replace(g, **changes)

    async def group_info(self, group_id: int) -> Group:
        self._need_connection()
        return self._group(group_id)

    async def set_group_title(self, group_id: int, title: str) -> None:
        self._need_connection()
        self._refresh(group_id, title=title)

    async def set_group_about(self, group_id: int, about: str) -> None:
        self._need_connection()
        self._refresh(group_id, about=about)

    async def add_members(self, group_id: int, user_ids: Sequence[int]) -> None:
        self._need_connection()
        self._group(group_id)
        for u in user_ids:
            self.group_members[group_id][u] = Member(u, f"user {u}", False)
        self._refresh(group_id)

    async def remove_member(self, group_id: int, user_id: int) -> None:
        self._need_connection()
        self._group(group_id)
        self.group_members[group_id].pop(user_id, None)
        self._refresh(group_id)

    async def set_admin(self, group_id: int, user_id: int, admin: bool) -> None:
        self._need_connection()
        self._group(group_id)
        m = self.group_members[group_id][user_id]
        self.group_members[group_id][user_id] = Member(m.user_id, m.name, admin)

    async def leave_group(self, group_id: int) -> None:
        self._need_connection()
        self._group(group_id)
        self.groups.pop(group_id)
        self.group_members.pop(group_id)

    async def group_link(self, group_id: int, revoke: bool = False) -> str:
        self._need_connection()
        g = self._group(group_id)
        if revoke:
            link = f"{g.invite_link}-new"
            self._refresh(group_id, invite_link=link)
            return link
        return g.invite_link or ""

    async def join_group(self, link: str) -> Group:
        self._need_connection()
        for g in self.groups.values():
            if g.invite_link and link.startswith(g.invite_link):
                return g
        from .errors import ChatNotFound

        raise ChatNotFound()

    async def members(self, group_id: int, limit: int = 100) -> List[Member]:
        self._need_connection()
        self._group(group_id)
        return list(self.group_members[group_id].values())[:limit]

    # ---- profile ---------------------------------------------------------------------------------------------

    async def set_name(self, name: str) -> None:
        self._need_connection()
        self.profile["name"] = name

    async def set_about(self, about: str) -> None:
        self._need_connection()
        self.profile["about"] = about

    async def set_username(self, username: str) -> None:
        self._need_connection()
        self.profile["username"] = username
