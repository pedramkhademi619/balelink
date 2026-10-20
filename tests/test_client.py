import asyncio

import pytest

from balesdk import (
    BaleClient,
    ChatNotFound,
    CodeNotRequested,
    ConnectionFailed,
    FileKind,
    NotLoggedIn,
    PasswordRequired,
    WrongCode,
    WrongPassword,
)
from balesdk import (
    filters as F,
)
from balesdk.testing import FakeTransport


def make(tmp_path, **kw):
    fake = FakeTransport(**kw)
    return fake, BaleClient("t", directory=tmp_path, transport=fake, min_send_interval=0)


# ---- login ---------------------------------------------------------------------------


async def test_login_flow(tmp_path):
    fake, c = make(tmp_path)
    assert not c.is_logged_in
    me = await c.login("09121234567", code=lambda: "12345")
    assert me.id == fake.me_id and c.is_logged_in
    assert fake.codes_requested == ["989121234567"]


async def test_login_with_async_code_provider(tmp_path):
    _, c = make(tmp_path)

    async def provide():
        return " 12345 "

    assert (await c.login("09121234567", code=provide)).id


async def test_wrong_code_retries_then_raises(tmp_path):
    _, c = make(tmp_path)
    tries = []

    def provide():
        tries.append(1)
        return "00000"

    with pytest.raises(WrongCode):
        await c.login("09121234567", code=provide, attempts=3)
    assert len(tries) == 3


async def test_wrong_code_literal_is_not_retried(tmp_path):
    _, c = make(tmp_path)
    with pytest.raises(WrongCode):
        await c.login("09121234567", code="0")


async def test_two_step_password(tmp_path):
    _, c = make(tmp_path, password="pw")
    with pytest.raises(PasswordRequired):
        await c.login("09121234567", code="12345")
    _, c = make(tmp_path, password="pw")
    with pytest.raises(WrongPassword):
        await c.login("09121234567", code="12345", password="bad")
    _, c = make(tmp_path, password="pw")
    assert (await c.login("09121234567", code="12345", password=lambda: "pw")).id


async def test_sign_in_without_request(tmp_path):
    _, c = make(tmp_path)
    with pytest.raises(CodeNotRequested):
        await c.sign_in("12345")


async def test_start_needs_login(tmp_path):
    _, c = make(tmp_path)
    with pytest.raises(NotLoggedIn):
        await c.start()


async def test_connection_failure_surfaces(tmp_path):
    fake, c = make(tmp_path, logged_in=True, fail_connect=True)
    with pytest.raises(ConnectionFailed):
        await c.start()
    assert c.last_error() == "connect_failed"


async def test_logout(tmp_path):
    fake, c = make(tmp_path, logged_in=True)
    await c.start()
    await c.logout()
    assert not c.is_logged_in and not c.is_connected


# ---- receiving ---------------------------------------------------------------------------


async def test_handlers_and_filters(bale, fake):
    got = []

    @bale.on_message(F.private & F.command("ping"))
    async def ping(m):
        got.append(("ping", m.text))
        await m.reply("pong")

    @bale.on_message(F.group)
    def group(m):
        got.append(("group", m.text))

    @bale.on_message()
    def every(m):
        got.append(("all", m.text))

    await fake.deliver("/ping")
    await fake.deliver("hi", kind=__import__("balesdk").ChatKind.GROUP)
    await asyncio.sleep(0.05)
    assert ("ping", "/ping") in got
    assert ("group", "hi") in got
    assert [t for k, t in got if k == "all"] == ["/ping", "hi"]
    assert fake.sent[0].text == "pong"


async def test_own_messages_not_delivered_by_default(bale, fake):
    got = []
    bale.on_message()(lambda m: got.append(m))
    await fake.deliver("mine", sender_id=fake.me_id)
    await asyncio.sleep(0.02)
    assert got == []


async def test_failing_handler_is_isolated_and_reported(bale, fake):
    seen, errors = [], []

    @bale.on_message()
    def bad(m):
        raise RuntimeError("boom")

    bale.on_message()(lambda m: seen.append(m.text))

    @bale.on_error
    def on_err(exc, msg):
        errors.append((str(exc), msg.text))

    await fake.deliver("x")
    await asyncio.sleep(0.05)
    assert seen == ["x"] and errors == [("boom", "x")]


async def test_message_stream_and_wait_for(bale, fake):
    waiter = asyncio.create_task(bale.wait_for(F.text_equals("go"), timeout=2))
    await asyncio.sleep(0.05)  # let it start listening (takes more loop turns on 3.9)
    await fake.deliver("nope")
    await fake.deliver("go")
    assert (await waiter).text == "go"

    with pytest.raises(asyncio.TimeoutError):
        await bale.wait_for(F.text_equals("never"), timeout=0.05)


async def test_stream_ends_on_stop(tmp_path):
    fake, c = make(tmp_path, logged_in=True)
    await c.start()
    seen = []

    async def consume():
        async for m in c.messages():
            seen.append(m.text)

    t = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await fake.deliver("a")
    await asyncio.sleep(0.02)
    await c.stop()
    await asyncio.wait_for(t, 1)
    assert seen == ["a"]


async def test_remove_handler(bale, fake):
    got = []
    fn = bale.on_message()(lambda m: got.append(1))
    assert bale.remove_handler(fn)
    assert not bale.remove_handler(fn)
    await fake.deliver("x")
    await asyncio.sleep(0.02)
    assert got == []


async def test_connection_callbacks(tmp_path):
    fake, c = make(tmp_path, logged_in=True)
    events = []
    c.on_ready(lambda: events.append("up"))
    c.on_disconnect(lambda: events.append("down"))
    await c.start()
    fake.drop_connection()
    await asyncio.sleep(0.8)
    fake.restore_connection()
    await asyncio.sleep(0.8)
    await c.stop()
    assert events == ["up", "down", "up"]


# ---- sending -------------------------------------------------------------------------------


async def test_send_to_phone_resolves_and_caches(bale, fake):
    await bale.send_text("09121234567", "hi")
    await bale.send_text("+98 912 123 4567", "again")
    assert [m.chat.id for m in fake.sent] == [777, 777]


async def test_send_to_unknown_phone(bale):
    with pytest.raises(ChatNotFound):
        await bale.send_text("09350000000", "x")
    with pytest.raises(ChatNotFound):
        await bale.send_text("12", "x")


async def test_long_text_is_split(bale, fake):
    last = await bale.send_text(5, "word " * 2000, limit=1000)
    assert len(fake.sent) > 1 and all(len(m.text) <= 1000 for m in fake.sent)
    assert last is fake.sent[-1]


async def test_split_can_be_turned_off(bale, fake):
    await bale.send_text(5, "x" * 9000, split=False)
    assert len(fake.sent) == 1


async def test_reply_edit_delete_react_seen(bale, fake):
    incoming = await fake.deliver("q", chat_id=9)
    sent = await incoming.reply("a")
    assert fake.sent[0].raw["reply_to"] == incoming.id
    await sent.edit("a2")
    await sent.react("👍")
    await sent.mark_seen()
    await sent.delete()
    assert fake.edits == [(sent.id, "a2")]
    assert fake.reactions == [(sent.id, "👍")]
    assert fake.seen[0].id == 9
    assert fake.deleted == [sent]


async def test_send_files(bale, fake):
    await bale.send_file(5, b"data", kind=FileKind.VOICE, caption="c", file_name="v.ogg")
    await bale.send_photo(5, b"img")
    assert [f.kind for f in fake.sent_files] == [FileKind.VOICE, FileKind.PHOTO]
    assert fake.sent_files[0].caption == "c"


async def test_typing_context(bale, fake):
    async with bale.typing(5):
        assert fake.typing_log == [(5, True)]
    assert fake.typing_log[-1] == (5, False)


async def test_history_and_download(bale, fake, tmp_path):
    m = await fake.deliver("a", chat_id=3)
    fake.history_store[3] = [m]
    assert (await bale.history(3))[0].text == "a"
    out = tmp_path / "f.bin"
    from balesdk import Attachment

    await bale.download(Attachment(file_id=1, access_hash=2), out)
    assert out.read_bytes() == b"fake-bytes"


async def test_resolve_types(bale):
    from balesdk import Chat, User

    assert (await bale.resolve(5)).id == 5
    assert (await bale.resolve(Chat(6))).id == 6
    assert (await bale.resolve(User(id=7))).id == 7
    with pytest.raises(TypeError):
        await bale.resolve(1.5)


async def test_send_pacing(tmp_path):
    fake = FakeTransport(logged_in=True)
    c = BaleClient("t", directory=tmp_path, transport=fake, min_send_interval=0.1)
    async with c:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await asyncio.gather(c.send_text(1, "a"), c.send_text(1, "b"), c.send_text(1, "c"))
        assert loop.time() - t0 >= 0.2


async def test_send_requires_connection(tmp_path):
    from balesdk import NotConnected

    fake, c = make(tmp_path, logged_in=True)
    with pytest.raises(NotConnected):
        await c.send_text(1, "x")


async def test_iter_history_pages_through_everything(bale, fake):
    from datetime import datetime, timedelta, timezone

    from balesdk import Chat, Message

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake.history_store[3] = [
        Message(id=i, chat=Chat(3), sender_id=3, date=base + timedelta(minutes=i), text=str(i))
        for i in range(1, 101)
    ]
    ids = [m.id async for m in bale.iter_history(3, page_size=30)]
    assert ids == list(range(100, 0, -1))
    capped = [m.id async for m in bale.iter_history(3, page_size=30, max_messages=5)]
    assert capped == [100, 99, 98, 97, 96]
