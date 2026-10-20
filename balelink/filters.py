"""Small, composable message filters.

    from balelink import filters as F

    @bale.on_message(F.private & F.command("start"))
    @bale.on_message(F.text_matches(r"price|قیمت") & ~F.from_me)

A filter is just a callable ``Message -> bool``; ``&``, ``|`` and ``~`` combine
them. Anything callable can be used where a filter is expected.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Callable, Union

from .models import Message


class Filter:
    def __init__(self, fn: Callable[[Message], bool], name: str = "filter") -> None:
        self._fn = fn
        self._name = name

    def __call__(self, message: Message) -> bool:
        return bool(self._fn(message))

    def __and__(self, other: Callable[[Message], bool]) -> Filter:
        return Filter(lambda m: self(m) and other(m), f"({self._name} & ...)")

    def __or__(self, other: Callable[[Message], bool]) -> Filter:
        return Filter(lambda m: self(m) or other(m), f"({self._name} | ...)")

    def __invert__(self) -> Filter:
        return Filter(lambda m: not self(m), f"~{self._name}")

    def __repr__(self) -> str:
        return f"<Filter {self._name}>"


def _f(name: str):
    def wrap(fn: Callable[[Message], bool]) -> Filter:
        return Filter(fn, name)

    return wrap


everything = Filter(lambda m: True, "everything")
text = Filter(lambda m: bool(m.text), "text")
private = Filter(lambda m: m.chat.is_private, "private")
group = Filter(lambda m: m.chat.is_group, "group")
from_me = Filter(lambda m: m.from_me, "from_me")
has_attachment = Filter(lambda m: m.has_attachment, "has_attachment")
location = Filter(lambda m: m.location is not None, "location")
photo = Filter(lambda m: m.kind == "photo", "photo")
voice = Filter(lambda m: m.kind == "voice", "voice")
video = Filter(lambda m: m.kind == "video", "video")
audio = Filter(lambda m: m.kind == "audio", "audio")
document = Filter(lambda m: m.kind == "document", "document")


def from_user(*user_ids: int) -> Filter:
    ids = set(user_ids)
    return Filter(lambda m: m.sender_id in ids, f"from_user{sorted(ids)}")


def in_chat(*chat_ids: int) -> Filter:
    ids = set(chat_ids)
    return Filter(lambda m: m.chat.id in ids, f"in_chat{sorted(ids)}")


def text_equals(value: str, *, ignore_case: bool = True) -> Filter:
    want = value.casefold() if ignore_case else value

    def check(m: Message) -> bool:
        if m.text is None:
            return False
        got = m.text.strip()
        return (got.casefold() if ignore_case else got) == want

    return Filter(check, f"text_equals({value!r})")


def text_contains(*words: str, ignore_case: bool = True) -> Filter:
    needles = [w.casefold() if ignore_case else w for w in words]

    def check(m: Message) -> bool:
        if not m.text:
            return False
        hay = m.text.casefold() if ignore_case else m.text
        return any(n in hay for n in needles)

    return Filter(check, f"text_contains{words}")


def text_matches(pattern: Union[str, re.Pattern[str]]) -> Filter:
    rx = re.compile(pattern) if isinstance(pattern, str) else pattern
    return Filter(lambda m: bool(m.text and rx.search(m.text)), f"text_matches({rx.pattern!r})")


def command(*names: str, prefix: str = "/") -> Filter:
    """``/start``, ``/help arg`` ... - the first word, case-insensitive."""
    wanted = {n.casefold() for n in names}

    def check(m: Message) -> bool:
        if not m.text or not m.text.startswith(prefix):
            return False
        first = m.text[len(prefix) :].split(maxsplit=1)
        return bool(first) and first[0].split("@", 1)[0].casefold() in wanted

    return Filter(check, f"command{names}")


def all_of(*filters: Callable[[Message], bool]) -> Filter:
    return Filter(lambda m: all(f(m) for f in filters), "all_of")


def any_of(*filters: Iterable[Callable[[Message], bool]]) -> Filter:
    return Filter(lambda m: any(f(m) for f in filters), "any_of")


def command_args(message: Message, *, prefix: str = "/") -> list[str]:
    """The words after a command: ``/send 123 hi`` -> ``['123', 'hi']``."""
    if not message.text or not message.text.startswith(prefix):
        return []
    return message.text.split()[1:]
