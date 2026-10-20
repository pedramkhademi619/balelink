"""The one thing balesdk needs from the outside world: a way to talk to Bale.

``BaleClient`` (the API you use) is written against this interface and never
imports a Bale library. The real implementation, ``AiobaleTransport``, wraps
the ``aiobale`` library; ``FakeTransport`` (in ``balesdk.testing``) lets you
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
    Me,
    Message,
    User,
)

MessageCallback = Callable[[Message], Awaitable[None]]


class Transport(Protocol):
    """Everything a Bale account can do, in balesdk's own types."""

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

    async def start(self, on_message: MessageCallback) -> None:
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
