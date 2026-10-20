"""The one thing balelink needs from the outside world: a way to talk to Bale.

``BaleClient`` (the API you use) is written against this interface and never
imports a Bale library. The real implementation, ``AiobaleTransport``, wraps
the ``aiobale`` library; ``FakeTransport`` (in ``balelink.testing``) lets you
test a bot with no network. If Bale changes, or you prefer another library,
you replace one class.
"""

from __future__ import annotations

import pathlib
from collections.abc import Awaitable, Sequence
from datetime import datetime
from typing import BinaryIO, Callable, List, Optional, Protocol, Union

from .models import (
    Attachment,
    Chat,
    CodeRequest,
    FileKind,
    FileSource,
    Group,
    Me,
    Member,
    Message,
    User,
)

MessageCallback = Callable[[Message], Awaitable[None]]
# (event name, payload) - "message.edited", "message.revoked", ...
EventCallback = Callable[[str, dict], Awaitable[None]]


class Transport(Protocol):
    """Everything a Bale account can do, in balelink's own types."""

    # ---- state ---------------------------------------------------------------

    @property
    def has_login(self) -> bool:
        """A saved login exists, so the account can start without a code."""

    @property
    def is_connected(self) -> bool:
        """The live connection to Bale is up right now."""

    @property
    def me(self) -> Optional[Me]:
        """The signed-in account, once known."""

    def last_error(self) -> Optional[str]:
        """A short code for why the connection last failed, or None."""

    # ---- signing in ----------------------------------------------------------

    async def request_code(self, phone: str) -> CodeRequest:
        """Ask Bale to send a login code to [phone] (already normalised).
        Raises an ``AuthError``."""

    async def sign_in(self, code: str, password: Optional[str]) -> Me:
        """Finish logging in; the login is saved. Raises an ``AuthError``."""

    async def sign_out(self) -> None:
        """Log out on Bale and delete the saved login."""

    # ---- connection ------------------------------------------------------------

    async def start(
        self, on_message: MessageCallback, on_event: Optional[EventCallback] = None
    ) -> None:
        """Connect and start delivering incoming messages. Raises
        ``ConnectionFailed`` if it can't connect. Reconnects on its own after."""

    async def stop(self) -> None:
        """Disconnect. The saved login is kept."""

    # ---- messages ----------------------------------------------------------------

    async def send_text(
        self, chat: Chat, text: str, reply_to: Optional[Message] = None
    ) -> Message: ...

    async def send_file(
        self,
        chat: Chat,
        file: FileSource,
        kind: FileKind,
        caption: Optional[str] = None,
        reply_to: Optional[Message] = None,
        file_name: Optional[str] = None,
    ) -> Message: ...

    async def send_location(
        self,
        chat: Chat,
        latitude: float,
        longitude: float,
        reply_to: Optional[Message] = None,
    ) -> Message: ...

    async def edit_text(self, message: Message, text: str) -> None: ...

    async def delete_messages(self, messages: Sequence[Message], just_me: bool = False) -> None: ...

    async def react(self, message: Message, emoji: str) -> None: ...

    async def mark_seen(self, chat: Chat) -> None: ...

    async def set_typing(self, chat: Chat, typing: bool) -> None: ...

    async def set_online(self, online: bool, timeout_seconds: int = 60) -> None: ...

    async def history(
        self, chat: Chat, limit: int = 20, before: Optional[datetime] = None
    ) -> List[Message]:
        """Newest first; with [before], only messages older than that."""

    async def download(
        self,
        attachment: Attachment,
        destination: Union[str, pathlib.Path, None] = None,
    ) -> Optional[BinaryIO]:
        """Save to [destination], or return the bytes in a file object."""

    # ---- people and chats ----------------------------------------------------------

    async def find_user_by_phone(self, phone: str) -> Optional[User]: ...

    async def get_user(self, chat: Chat) -> Optional[User]: ...

    async def dialogs(self, limit: int = 40) -> List[Chat]: ...

    # ---- more message actions -------------------------------------------------------

    async def forward_messages(self, messages: Sequence[Message], to: Chat) -> None: ...

    async def pin_message(self, message: Message, just_me: bool = False) -> None: ...

    async def unpin_message(self, message: Message) -> None: ...

    async def unreact(self, message: Message, emoji: str) -> None: ...

    async def delete_chat(self, chat: Chat) -> None: ...

    async def clear_chat(self, chat: Chat) -> None: ...

    # ---- contacts ------------------------------------------------------------------

    async def contacts(self) -> List[User]: ...

    async def add_contact(self, user_id: int) -> None: ...

    async def remove_contact(self, user_id: int) -> None: ...

    async def rename_contact(self, user_id: int, name: str) -> None: ...

    async def block(self, user_id: int) -> None: ...

    async def unblock(self, user_id: int) -> None: ...

    async def blocked(self) -> List[User]: ...

    async def user_info(self, user_id: int) -> Optional[User]: ...

    # ---- groups ----------------------------------------------------------------------

    async def create_group(self, title: str, user_ids: Sequence[int]) -> Group: ...

    async def group_info(self, group_id: int) -> Group: ...

    async def set_group_title(self, group_id: int, title: str) -> None: ...

    async def set_group_about(self, group_id: int, about: str) -> None: ...

    async def add_members(self, group_id: int, user_ids: Sequence[int]) -> None: ...

    async def remove_member(self, group_id: int, user_id: int) -> None: ...

    async def set_admin(self, group_id: int, user_id: int, admin: bool) -> None: ...

    async def leave_group(self, group_id: int) -> None: ...

    async def group_link(self, group_id: int, revoke: bool = False) -> str: ...

    async def join_group(self, link: str) -> Group: ...

    async def members(self, group_id: int, limit: int = 100) -> List[Member]: ...

    # ---- my profile ----------------------------------------------------------------------

    async def set_name(self, name: str) -> None: ...

    async def set_about(self, about: str) -> None: ...

    async def set_username(self, username: str) -> None: ...
