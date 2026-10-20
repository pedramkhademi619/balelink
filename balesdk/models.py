"""The objects the library hands you.

They are plain dataclasses, independent of any transport, so your code (and
your tests) never touches Bale's wire types.
"""

from __future__ import annotations

import enum
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, BinaryIO, Optional, Union

if TYPE_CHECKING:  # pragma: no cover
    from .client import BaleClient

FileSource = Union[str, pathlib.Path, bytes, BinaryIO]


class ChatKind(str, enum.Enum):
    PRIVATE = "private"
    GROUP = "group"
    SUPER_GROUP = "super_group"
    CHANNEL = "channel"
    BOT = "bot"
    UNKNOWN = "unknown"


class FileKind(str, enum.Enum):
    """How a file is sent: as a plain document, or as media."""

    DOCUMENT = "document"
    PHOTO = "photo"
    VIDEO = "video"
    VOICE = "voice"
    AUDIO = "audio"
    GIF = "gif"


@dataclass(frozen=True)
class Chat:
    """A conversation: a person, a group, a channel. ``id`` is Bale's own id
    (for a private chat it is the other person's user id)."""

    id: int
    kind: ChatKind = ChatKind.PRIVATE

    @property
    def is_private(self) -> bool:
        return self.kind in (ChatKind.PRIVATE, ChatKind.BOT)

    @property
    def is_group(self) -> bool:
        return self.kind in (ChatKind.GROUP, ChatKind.SUPER_GROUP)


@dataclass(frozen=True)
class User:
    id: int
    name: str = ""
    username: Optional[str] = None
    is_bot: bool = False

    @property
    def chat(self) -> Chat:
        return Chat(self.id, ChatKind.BOT if self.is_bot else ChatKind.PRIVATE)


@dataclass(frozen=True)
class Me:
    """The signed-in account."""

    id: int
    phone: Optional[str] = None
    name: Optional[str] = None


@dataclass(frozen=True)
class Attachment:
    """A file that came with a message."""

    file_id: int
    access_hash: int
    name: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None


@dataclass(frozen=True)
class CodeRequest:
    """What asking for a login code tells you."""

    phone: str
    timeout_seconds: Optional[int] = None


@dataclass(eq=False)
class Message:
    """One message, with shortcuts to act on it (``reply``, ``react``, ...).

    ``raw`` is the transport's own object, kept so a reply can quote exactly
    this message; treat it as opaque.
    """

    id: int
    chat: Chat
    sender_id: int
    date: datetime
    text: Optional[str] = None
    attachment: Optional[Attachment] = None
    from_me: bool = False
    raw: Any = field(default=None, repr=False)
    _client: Optional[BaleClient] = field(default=None, repr=False)

    @property
    def timestamp(self) -> float:
        return self.date.timestamp()

    @property
    def has_attachment(self) -> bool:
        return self.attachment is not None

    @staticmethod
    def from_millis(ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

    # ---- shortcuts ---------------------------------------------------------------

    def _need_client(self) -> BaleClient:
        if self._client is None:
            raise RuntimeError("This message is not attached to a client")
        return self._client

    async def reply(self, text: str) -> Message:
        """Send [text] in this chat, quoting this message."""
        return await self._need_client().send_text(self.chat, text, reply_to=self)

    async def reply_file(
        self,
        file: FileSource,
        *,
        kind: FileKind = FileKind.DOCUMENT,
        caption: Optional[str] = None,
    ) -> Message:
        return await self._need_client().send_file(
            self.chat, file, kind=kind, caption=caption, reply_to=self
        )

    async def edit(self, text: str) -> None:
        await self._need_client().edit_text(self, text)

    async def delete(self, *, just_me: bool = False) -> None:
        await self._need_client().delete_messages([self], just_me=just_me)

    async def react(self, emoji: str) -> None:
        await self._need_client().react(self, emoji)

    async def mark_seen(self) -> None:
        await self._need_client().mark_seen(self.chat)

    async def download(self, destination: Union[str, pathlib.Path, None] = None):
        """Save the attachment to [destination] (or return it in memory)."""
        if self.attachment is None:
            raise ValueError("This message has no attachment")
        return await self._need_client().download(self.attachment, destination)
