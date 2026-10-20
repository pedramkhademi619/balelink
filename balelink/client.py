"""``BaleClient`` - the API you use.

async with BaleClient("me") as bale:
    if not bale.is_logged_in:
        await bale.login("09121234567", code=lambda: input("code: "))

    @bale.on_message(F.private & F.command("start"))
    async def hello(msg):
        await msg.reply("hi!")

    await bale.send_text("09127654321", "hello")
    await bale.run_forever()
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import pathlib
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import (
    Any,
    BinaryIO,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)

from . import filters as F
from .errors import (
    AlreadyLoggedIn,
    ChatNotFound,
    NotLoggedIn,
    PasswordRequired,
    WrongCode,
)
from .models import (
    Attachment,
    Chat,
    ChatKind,
    CodeRequest,
    FileKind,
    FileSource,
    Group,
    Me,
    Member,
    Message,
    User,
)
from .phone import is_plausible_phone, normalize_phone
from .store import SessionStore
from .text import DEFAULT_LIMIT, split_text
from .transport import Transport

log = logging.getLogger("balelink")

Target = Union[Chat, Message, User, int, str]
Handler = Callable[[Message], Union[Awaitable[None], None]]
Provider = Union[str, Callable[[], Union[str, Awaitable[str]]]]


async def _resolve_provider(provider: Provider) -> str:
    value = provider() if callable(provider) else provider
    if inspect.isawaitable(value):
        value = await value
    return str(value).strip()


class _Registered:
    __slots__ = ("fn", "filter")

    def __init__(self, fn: Handler, flt: Callable[[Message], bool]) -> None:
        self.fn = fn
        self.filter = flt


class BaleClient:
    """One Bale personal account.

    Args:
        session: A name for the saved login (letters, digits, ``_-.``).
        directory: Where logins are kept (default ``~/.balelink``, or
            ``$BALELINK_HOME``).
        min_send_interval: Seconds to wait between sends. Bale may restrict an
            account that sends in bursts; keep a small gap.
        deliver_own: Also hand your own messages to handlers.
        transport: Replace the Bale connection (tests use ``FakeTransport``).
    """

    def __init__(
        self,
        session: str = "default",
        *,
        directory: Union[str, pathlib.Path, None] = None,
        min_send_interval: float = 0.4,
        deliver_own: bool = False,
        transport: Optional[Transport] = None,
    ) -> None:
        self.store = SessionStore(directory)
        self.session_name = self.store.check_name(session)
        self.min_send_interval = min_send_interval
        self.deliver_own = deliver_own

        if transport is None:
            from ._aiobale import AiobaleTransport

            transport = AiobaleTransport(self.session_name, self.store)
        self._transport: Transport = transport

        self._handlers: List[_Registered] = []
        self._streams: List[asyncio.Queue[Message]] = []
        self._ready_callbacks: List[Callable[[], Any]] = []
        self._lost_callbacks: List[Callable[[], Any]] = []
        self._error_callbacks: List[Callable[[BaseException, Message], Any]] = []
        self._edited_handlers: List[_Registered] = []
        self._deleted_handlers: List[Callable[..., Any]] = []
        self._event_listeners: List[Callable[[str, dict], Any]] = []
        self._tasks: set[asyncio.Task[Any]] = set()

        # Created on first use, inside the running loop: on Python 3.9 a Lock or
        # Event made earlier binds to whatever loop happens to be current.
        self._send_lock_obj: Optional[asyncio.Lock] = None
        self._last_send = 0.0
        self._phone_cache: Dict[str, Chat] = self._load_phones()
        self._started = False
        self._stopping_obj: Optional[asyncio.Event] = None
        self._monitor: Optional[asyncio.Task[None]] = None

    @property
    def _send_lock(self) -> asyncio.Lock:
        if self._send_lock_obj is None:
            self._send_lock_obj = asyncio.Lock()
        return self._send_lock_obj

    @property
    def _stopping(self) -> asyncio.Event:
        if self._stopping_obj is None:
            self._stopping_obj = asyncio.Event()
        return self._stopping_obj

    # ---- state ------------------------------------------------------------------------

    @property
    def is_logged_in(self) -> bool:
        """A saved login exists (it may still need a connection)."""
        return self._transport.has_login

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    @property
    def me(self) -> Optional[Me]:
        return self._transport.me

    def last_error(self) -> Optional[str]:
        return self._transport.last_error()

    # ---- logging in ----------------------------------------------------------------------

    async def request_code(self, phone: str) -> CodeRequest:
        """Ask Bale to send a login code to [phone] (``0912...``/``+98...``)."""
        from .errors import InvalidPhone

        number = normalize_phone(phone)
        if not is_plausible_phone(number):
            raise InvalidPhone()
        if self.is_logged_in and self.is_connected:
            raise AlreadyLoggedIn()
        return await self._transport.request_code(number)

    async def sign_in(self, code: str, *, password: Optional[str] = None) -> Me:
        """Finish logging in with the code Bale sent. Raises ``WrongCode``,
        ``PasswordRequired`` (call again with ``password=``) and friends."""
        return await self._transport.sign_in(str(code).strip(), password)

    async def login(
        self,
        phone: str,
        *,
        code: Provider,
        password: Optional[Provider] = None,
        attempts: int = 3,
    ) -> Me:
        """The whole login in one call.

        ``code`` is the code itself, or a function returning it (it may be
        ``async``; ``lambda: input("code: ")`` works). It is called after Bale
        has sent the code. ``password`` is the two-step password, or a function
        for it, used only if the account has one. A wrong code asks again, up
        to [attempts] times.
        """
        await self.request_code(phone)
        last: Optional[Exception] = None
        for _ in range(max(1, attempts)):
            entered = await _resolve_provider(code)
            try:
                try:
                    return await self.sign_in(entered)
                except PasswordRequired:
                    if password is None:
                        raise
                    return await self.sign_in(entered, password=await _resolve_provider(password))
            except WrongCode as e:
                last = e
                if not callable(code):
                    break
        assert last is not None
        raise last

    async def logout(self) -> None:
        """Log out and delete the saved login."""
        await self.stop()
        await self._transport.sign_out()

    # ---- running -----------------------------------------------------------------------------

    async def start(self) -> BaleClient:
        """Connect and start receiving. Needs a saved login."""
        if self._started:
            return self
        if not self.is_logged_in:
            raise NotLoggedIn()
        await self._transport.start(self._on_incoming, self._on_transport_event)
        self._started = True
        self._stopping.clear()
        self._monitor = asyncio.create_task(self._watch_connection(self.is_connected))
        await self._call_all(self._ready_callbacks)
        return self

    async def stop(self) -> None:
        """Disconnect. The saved login stays."""
        if not self._started and not self._transport.is_connected:
            return
        self._started = False
        self._stopping.set()
        if self._monitor is not None:
            self._monitor.cancel()
            try:
                await self._monitor
            except asyncio.CancelledError:
                pass
            self._monitor = None
        for t in list(self._tasks):
            t.cancel()
        await self._transport.stop()
        for q in self._streams:
            q.put_nowait(_STOP)  # type: ignore[arg-type]

    async def run_forever(self) -> None:
        """Block until ``stop()`` (or Ctrl-C), handling messages meanwhile."""
        if not self._started:
            await self.start()
        try:
            await self._stopping.wait()
        except asyncio.CancelledError:
            raise
        finally:
            await self.stop()

    async def wait_until_connected(self, timeout: float = 30.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.is_connected:
                return True
            await asyncio.sleep(0.05)
        return self.is_connected

    async def __aenter__(self) -> BaleClient:
        if self.is_logged_in:
            await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    async def _watch_connection(self, was: bool) -> None:
        """Report drops and recoveries (the transport reconnects by itself)."""
        while True:
            await asyncio.sleep(0.5)
            now = self.is_connected
            if now and not was:
                await self._call_all(self._ready_callbacks)
                await self._emit("connection.up", {})
            elif was and not now:
                await self._call_all(self._lost_callbacks)
                await self._emit("connection.down", {})
            was = now

    # ---- receiving ---------------------------------------------------------------------------------

    def on_message(self, *filters: Callable[[Message], bool]) -> Callable[[Handler], Handler]:
        """Register a handler: ``@bale.on_message(F.private & F.text)``.

        With no filter it gets every incoming message. Handlers may be
        ``async`` or plain functions; one that raises does not affect the
        others (see ``on_error``).
        """
        combined = F.all_of(*filters) if filters else F.everything

        def register(fn: Handler) -> Handler:
            self._handlers.append(_Registered(fn, combined))
            return fn

        return register

    def on_edited(self, *filters: Callable[[Message], bool]) -> Callable[[Handler], Handler]:
        """``@bale.on_edited(F.private)`` - called with the message after an edit."""
        combined = F.all_of(*filters) if filters else F.everything

        def register(fn: Handler) -> Handler:
            self._edited_handlers.append(_Registered(fn, combined))
            return fn

        return register

    def on_deleted(self, fn: Callable[[Chat, List[int]], Any]):
        """Called with ``(chat, message_ids)`` when messages are deleted."""
        self._deleted_handlers.append(fn)
        return fn

    def on_event(self, fn: Callable[[str, dict], Any]):
        """Every event as ``(name, payload)``: ``message``, ``message.edited``,
        ``message.revoked``, ``connection.up``, ``connection.down``. This is what
        the gateway turns into webhooks."""
        self._event_listeners.append(fn)
        return fn

    async def _emit(self, name: str, payload: dict) -> None:
        for fn in list(self._event_listeners):
            await self._call_one(fn, name, payload)

    async def _on_transport_event(self, name: str, payload: dict) -> None:
        if name == "message.edited":
            message: Message = payload["message"]
            message._client = self
            for h in list(self._edited_handlers):
                try:
                    if h.filter(message):
                        task = asyncio.create_task(self._run_handler(h.fn, message))
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)
                except Exception:
                    log.exception("a filter raised")
        elif name == "message.revoked":
            for fn in list(self._deleted_handlers):
                await self._call_one(fn, payload["chat"], payload["ids"])
        await self._emit(name, payload)

    def remove_handler(self, fn: Handler) -> bool:
        before = len(self._handlers)
        self._handlers = [h for h in self._handlers if h.fn is not fn]
        return len(self._handlers) != before

    def on_ready(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        """Called when the connection comes up, first time and after drops."""
        self._ready_callbacks.append(fn)
        return fn

    def on_disconnect(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self._lost_callbacks.append(fn)
        return fn

    def on_error(self, fn: Callable[[BaseException, Message], Any]):
        """Called with ``(exception, message)`` when a handler raises."""
        self._error_callbacks.append(fn)
        return fn

    async def messages(self, *filters: Callable[[Message], bool]) -> AsyncIterator[Message]:
        """``async for msg in bale.messages(F.private): ...`` - incoming
        messages as a stream. Ends when the client stops."""
        flt = F.all_of(*filters) if filters else F.everything
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._streams.append(queue)
        try:
            while True:
                item = await queue.get()
                if item is _STOP:
                    return
                if flt(item):
                    yield item
        finally:
            self._streams.remove(queue)

    async def wait_for(
        self,
        *filters: Callable[[Message], bool],
        timeout: Optional[float] = None,
    ) -> Message:
        """The next incoming message that passes [filters] (``TimeoutError``
        after [timeout] seconds)."""

        async def first() -> Message:
            async for m in self.messages(*filters):
                return m
            raise asyncio.CancelledError  # the client stopped

        return await asyncio.wait_for(first(), timeout)

    async def _on_incoming(self, message: Message) -> None:
        message._client = self
        await self._emit("message.any", {"message": message})
        if message.from_me and not self.deliver_own:
            return
        await self._emit("message", {"message": message})
        for q in self._streams:
            q.put_nowait(message)
        for h in list(self._handlers):
            try:
                if not h.filter(message):
                    continue
            except Exception:
                log.exception("a filter raised")
                continue
            task = asyncio.create_task(self._run_handler(h.fn, message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_handler(self, fn: Handler, message: Message) -> None:
        try:
            result = fn(message)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self._error_callbacks:
                for cb in self._error_callbacks:
                    await self._call_one(cb, e, message)
            else:
                log.exception("a message handler failed")

    async def _call_all(self, callbacks: Sequence[Callable[[], Any]]) -> None:
        for cb in callbacks:
            await self._call_one(cb)

    @staticmethod
    async def _call_one(cb: Callable[..., Any], *args: Any) -> None:
        try:
            r = cb(*args)
            if inspect.isawaitable(r):
                await r
        except Exception:
            log.exception("a callback raised")

    # ---- targets ----------------------------------------------------------------------------------------

    async def resolve(self, target: Target) -> Chat:
        """Turn whatever you have into a ``Chat``: a ``Chat``, a ``Message``
        (its chat), a ``User``, a user id, or a phone number."""
        if isinstance(target, Chat):
            return target
        if isinstance(target, Message):
            return target.chat
        if isinstance(target, User):
            return target.chat
        if isinstance(target, int):
            return Chat(target, ChatKind.PRIVATE)
        if isinstance(target, str):
            return await self._chat_for_phone(target)
        raise TypeError(f"Can't turn {type(target).__name__} into a chat")

    # Bale throttles phone-number lookups (observed: after a couple in a row it
    # answers "not found" even for numbers it just found), so what we learn is
    # kept on disk and reused.
    def _phones_path(self) -> pathlib.Path:
        return self.store.directory / f"{self.session_name}.phones.json"

    def _load_phones(self) -> Dict[str, Chat]:
        try:
            data = json.loads(self._phones_path().read_text("utf-8"))
            return {str(k): Chat(int(v), ChatKind.PRIVATE) for k, v in data.items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save_phones(self) -> None:
        try:
            self.store.ensure_directory()
            path = self._phones_path()
            path.write_text(json.dumps({k: c.id for k, c in self._phone_cache.items()}), "utf-8")
            os.chmod(path, 0o600)
        except OSError:
            log.debug("could not save the phone cache", exc_info=True)

    def remember_phone(self, phone: str, user_id: int) -> None:
        """Teach the client that [phone] is [user_id] (skips a lookup)."""
        self._phone_cache[normalize_phone(phone)] = Chat(user_id, ChatKind.PRIVATE)
        self._save_phones()

    def forget_phone(self, phone: str) -> None:
        if self._phone_cache.pop(normalize_phone(phone), None) is not None:
            self._save_phones()

    async def _chat_for_phone(self, raw: str) -> Chat:
        phone = normalize_phone(raw)
        if not is_plausible_phone(phone):
            raise ChatNotFound(f"'{raw}' is not a phone number")
        if phone in self._phone_cache:
            return self._phone_cache[phone]
        user = await self._transport.find_user_by_phone(phone)
        if user is None:
            raise ChatNotFound(f"No Bale user has the number {phone}")
        chat = user.chat
        self._phone_cache[phone] = chat
        self._save_phones()
        return chat

    # ---- sending ------------------------------------------------------------------------------------------

    async def _paced(self) -> None:
        """Serialise sends and keep a gap between them."""
        loop = asyncio.get_running_loop()
        wait = self._last_send + self.min_send_interval - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_send = loop.time()

    async def send_text(
        self,
        target: Target,
        text: str,
        *,
        reply_to: Optional[Message] = None,
        split: bool = True,
        limit: int = DEFAULT_LIMIT,
    ) -> Message:
        """Send [text]. A long text is sent as several messages (set
        ``split=False`` to send it whole). Returns the last message sent."""
        chat = await self.resolve(target)
        parts = split_text(text, limit) if split else [text]
        sent: Optional[Message] = None
        async with self._send_lock:
            for i, part in enumerate(parts):
                await self._paced()
                sent = await self._transport.send_text(chat, part, reply_to if i == 0 else None)
                sent._client = self
        assert sent is not None
        return sent

    async def send_file(
        self,
        target: Target,
        file: FileSource,
        *,
        kind: FileKind = FileKind.DOCUMENT,
        caption: Optional[str] = None,
        reply_to: Optional[Message] = None,
        file_name: Optional[str] = None,
    ) -> Message:
        """Send a file: a path, ``bytes`` or an open binary file. ``kind``
        chooses how it appears (document, photo, video, voice, audio, gif)."""
        chat = await self.resolve(target)
        async with self._send_lock:
            await self._paced()
            sent = await self._transport.send_file(chat, file, kind, caption, reply_to, file_name)
        sent._client = self
        return sent

    async def send_photo(self, target: Target, file: FileSource, **kw: Any) -> Message:
        return await self.send_file(target, file, kind=FileKind.PHOTO, **kw)

    async def send_location(
        self,
        target: Target,
        latitude: float,
        longitude: float,
        *,
        reply_to: Optional[Message] = None,
    ) -> Message:
        """Send a map point."""
        from .models import Location

        Location(latitude, longitude)  # validates the range
        chat = await self.resolve(target)
        async with self._send_lock:
            await self._paced()
            sent = await self._transport.send_location(chat, latitude, longitude, reply_to)
        sent._client = self
        return sent

    async def edit_text(self, message: Message, text: str) -> None:
        await self._transport.edit_text(message, text)

    async def delete_messages(self, messages: Sequence[Message], *, just_me: bool = False) -> None:
        await self._transport.delete_messages(messages, just_me)

    async def react(self, message: Message, emoji: str) -> None:
        await self._transport.react(message, emoji)

    async def mark_seen(self, target: Target) -> None:
        await self._transport.mark_seen(await self.resolve(target))

    async def set_online(self, online: bool = True, *, timeout_seconds: int = 60) -> None:
        await self._transport.set_online(online, timeout_seconds)

    @asynccontextmanager
    async def typing(self, target: Target) -> AsyncIterator[None]:
        """Show "typing..." while you work: ``async with bale.typing(msg): ...``"""
        chat = await self.resolve(target)
        await self._transport.set_typing(chat, True)
        try:
            yield
        finally:
            try:
                await self._transport.set_typing(chat, False)
            except Exception:
                log.debug("could not clear the typing indicator", exc_info=True)

    # ---- forwarding, pinning, chats ----------------------------------------------------------------

    async def forward_messages(self, messages: Sequence[Message], to: Target) -> None:
        """Forward [messages] to another chat."""
        chat = await self.resolve(to)
        async with self._send_lock:
            await self._paced()
            await self._transport.forward_messages(list(messages), chat)

    async def pin_message(self, message: Message, *, just_me: bool = False) -> None:
        await self._transport.pin_message(message, just_me)

    async def unpin_message(self, message: Message) -> None:
        await self._transport.unpin_message(message)

    async def unreact(self, message: Message, emoji: str) -> None:
        await self._transport.unreact(message, emoji)

    async def delete_chat(self, target: Target) -> None:
        await self._transport.delete_chat(await self.resolve(target))

    async def clear_chat(self, target: Target) -> None:
        """Remove every message from a chat (for you)."""
        await self._transport.clear_chat(await self.resolve(target))

    # ---- contacts ---------------------------------------------------------------------------------------

    async def _user_id(self, who: Union[Target, Member]) -> int:
        if isinstance(who, Member):
            return who.user_id
        if isinstance(who, Message):
            return who.sender_id
        return (await self.resolve(who)).id

    async def check_phone(self, phone: str) -> Optional[User]:
        """Is this number on Bale? Returns the user, or ``None``."""
        number = normalize_phone(phone)
        cached = self._phone_cache.get(number)
        if cached is not None:
            return User(id=cached.id)
        found = await self._transport.find_user_by_phone(number)
        if found is not None:
            self.remember_phone(number, found.id)
        return found

    async def contacts(self) -> List[User]:
        return await self._transport.contacts()

    async def add_contact(self, who: Target) -> None:
        await self._transport.add_contact(await self._user_id(who))

    async def remove_contact(self, who: Target) -> None:
        await self._transport.remove_contact(await self._user_id(who))

    async def rename_contact(self, who: Target, name: str) -> None:
        await self._transport.rename_contact(await self._user_id(who), name)

    async def block(self, who: Target) -> None:
        await self._transport.block(await self._user_id(who))

    async def unblock(self, who: Target) -> None:
        await self._transport.unblock(await self._user_id(who))

    async def blocked(self) -> List[User]:
        return await self._transport.blocked()

    async def user_info(self, who: Target) -> Optional[User]:
        """Name, username, about, and whether they are a contact / blocked."""
        return await self._transport.user_info(await self._user_id(who))

    # ---- groups -----------------------------------------------------------------------------------------------

    async def create_group(self, title: str, members: Sequence[Target] = ()) -> Group:
        """Make a group and invite [members] (phone numbers, ids or Users)."""
        ids = [await self._user_id(m) for m in members]
        return await self._transport.create_group(title, ids)

    async def group_info(self, group: Union[Group, Chat, int]) -> Group:
        return await self._transport.group_info(self._group_id(group))

    @staticmethod
    def _group_id(group: Union[Group, Chat, int]) -> int:
        return group if isinstance(group, int) else group.id

    async def set_group_title(self, group: Union[Group, Chat, int], title: str) -> None:
        await self._transport.set_group_title(self._group_id(group), title)

    async def set_group_about(self, group: Union[Group, Chat, int], about: str) -> None:
        await self._transport.set_group_about(self._group_id(group), about)

    async def add_members(self, group: Union[Group, Chat, int], members: Sequence[Target]) -> None:
        ids = [await self._user_id(m) for m in members]
        await self._transport.add_members(self._group_id(group), ids)

    async def remove_member(self, group: Union[Group, Chat, int], who: Target) -> None:
        await self._transport.remove_member(self._group_id(group), await self._user_id(who))

    async def set_admin(
        self, group: Union[Group, Chat, int], who: Target, admin: bool = True
    ) -> None:
        await self._transport.set_admin(self._group_id(group), await self._user_id(who), admin)

    async def leave_group(self, group: Union[Group, Chat, int]) -> None:
        await self._transport.leave_group(self._group_id(group))

    async def group_link(self, group: Union[Group, Chat, int], *, revoke: bool = False) -> str:
        """The invite link; ``revoke=True`` makes a new one and kills the old."""
        return await self._transport.group_link(self._group_id(group), revoke)

    async def join_group(self, link: str) -> Group:
        return await self._transport.join_group(link)

    async def members(self, group: Union[Group, Chat, int], limit: int = 100) -> List[Member]:
        return await self._transport.members(self._group_id(group), limit)

    # ---- my profile -----------------------------------------------------------------------------------------------

    async def set_name(self, name: str) -> None:
        await self._transport.set_name(name)

    async def set_about(self, about: str) -> None:
        await self._transport.set_about(about)

    async def set_username(self, username: str) -> None:
        await self._transport.set_username(username)

    # ---- reading ----------------------------------------------------------------------------------------------

    async def history(
        self, target: Target, limit: int = 20, *, before: Optional[datetime] = None
    ) -> List[Message]:
        """Messages of a chat, newest first. Bale returns at most a page at a
        time (about 40); pass ``before=`` the date of the oldest one you have
        to get the page before it, or use ``iter_history``."""
        chat = await self.resolve(target)
        found = await self._transport.history(chat, limit, before)
        for m in found:
            m._client = self
        return found

    async def iter_history(
        self, target: Target, *, page_size: int = 40, max_messages: Optional[int] = None
    ) -> AsyncIterator[Message]:
        """The whole chat, newest first, page by page:
        ``async for m in bale.iter_history(chat): ...``"""
        chat = await self.resolve(target)
        before: Optional[datetime] = None
        seen: set = set()
        yielded = 0
        while True:
            page = [
                m for m in await self.history(chat, page_size, before=before) if m.id not in seen
            ]
            if not page:
                return
            for m in page:
                seen.add(m.id)
                yield m
                yielded += 1
                if max_messages is not None and yielded >= max_messages:
                    return
            oldest = min(m.date for m in page)
            if before is not None and oldest >= before:
                return  # no progress - stop rather than loop forever
            before = oldest

    async def download(
        self,
        attachment: Attachment,
        destination: Union[str, pathlib.Path, None] = None,
    ) -> Optional[BinaryIO]:
        return await self._transport.download(attachment, destination)

    async def get_user(self, target: Target) -> Optional[User]:
        return await self._transport.get_user(await self.resolve(target))

    async def dialogs(self, limit: int = 40) -> List[Chat]:
        """Your chats, most recent first."""
        return await self._transport.dialogs(limit)


class _Stop:
    def __repr__(self) -> str:  # pragma: no cover
        return "<stop>"


_STOP = _Stop()
