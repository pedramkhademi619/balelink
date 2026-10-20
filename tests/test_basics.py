import pytest

from balelink import (
    Chat,
    ChatKind,
    InvalidPhone,
    SessionStore,
    is_plausible_phone,
    normalize_phone,
    split_text,
)
from balelink import (
    filters as F,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("09121234567", "989121234567"),
        ("+98 912 123 4567", "989121234567"),
        ("0098-912-123-4567", "989121234567"),
        ("۰۹۱۲۱۲۳۴۵۶۷", "989121234567"),
        ("989121234567", "989121234567"),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_plausible_phone():
    assert is_plausible_phone("989121234567")
    assert not is_plausible_phone("123")
    assert not is_plausible_phone("")


def test_split_text_short_is_untouched():
    assert split_text("hello", 10) == ["hello"]


def test_split_text_prefers_boundaries_and_loses_nothing():
    text = ("word " * 50).strip()
    parts = split_text(text, 40)
    assert all(len(p) <= 40 for p in parts)
    assert " ".join(parts).split() == text.split()


def test_split_text_long_word_is_cut():
    parts = split_text("x" * 25, 10)
    assert parts == ["x" * 10, "x" * 10, "x" * 5]


def test_split_rejects_bad_limit():
    with pytest.raises(ValueError):
        split_text("a", 0)


def test_store_permissions_and_names(tmp_path):
    store = SessionStore(tmp_path / "s")
    store.ensure_directory()
    assert oct(store.directory.stat().st_mode & 0o777) == "0o700"
    p = store.path("me")
    p.write_text("secret")
    store.secure("me")
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert store.names() == ["me"]
    assert store.exists("me")
    store.delete("me")
    assert not store.exists("me")
    for bad in ("", "../x", "a/b", "a b"):
        with pytest.raises(ValueError):
            store.check_name(bad)


def _msg(fake_text, kind=ChatKind.PRIVATE, sender=1, chat=1):
    from datetime import datetime, timezone

    from balelink import Message

    return Message(
        id=1,
        chat=Chat(chat, kind),
        sender_id=sender,
        date=datetime.now(timezone.utc),
        text=fake_text,
    )


def test_filters_compose():
    m = _msg("/start hello world")
    assert F.command("start")(m)
    assert not F.command("stop")(m)
    assert (F.private & F.text)(m)
    assert not (F.group | F.from_me)(m)
    assert (~F.group)(m)
    assert F.command_args(m) == ["hello", "world"]
    assert F.text_contains("HELLO")(m)
    assert F.text_equals("/START hello world")(m)
    assert F.text_matches(r"world$")(m)
    assert F.from_user(1)(m) and not F.from_user(2)(m)
    assert F.in_chat(1)(m)
    assert not F.text(_msg(None))


def test_command_ignores_bot_suffix_and_prefix():
    assert F.command("go")(_msg("/go@somebot x"))
    assert not F.command("go")(_msg("go"))
    assert F.command("go", prefix="!")(_msg("!go"))


async def test_request_code_validates_phone(tmp_path):
    from balelink import BaleClient
    from balelink.testing import FakeTransport

    c = BaleClient("t", directory=tmp_path, transport=FakeTransport())
    with pytest.raises(InvalidPhone):
        await c.request_code("12")
