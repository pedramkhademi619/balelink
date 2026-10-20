# Guide

Everything is `async`; run it with `asyncio.run(...)`.

## The client

```python
bale = BaleClient(
    "me",  # which saved login
    directory=None,  # default ~/.balesdk (or $BALESDK_HOME)
    min_send_interval=0.4,  # seconds between sends
    deliver_own=False,  # also pass your own messages to handlers
)
```

`async with bale:` connects if a login exists and disconnects at the end.
Without `async with`, call `await bale.start()` and `await bale.stop()`.
Reconnecting after a drop is automatic; `@bale.on_ready` and
`@bale.on_disconnect` tell you when.

## Logging in from code

```python
if not bale.is_logged_in:
    await bale.login(
        "09121234567",
        code=lambda: input("code: "),  # or an async function
        password=lambda: input("password: "),
    )  # only asked if needed
```

`code` and `password` can be strings or functions (sync or async), so you can
fetch them from a web form or a chat. A wrong code asks again up to `attempts=3`
times. Doing it in two steps:

```python
await bale.request_code(phone)
await bale.sign_in(code)  # raises PasswordRequired if the account has one
await bale.sign_in(code, password="...")
```

`await bale.logout()` signs out and deletes the saved login.

## Receiving

```python
@bale.on_message(F.private & F.text)
async def on_text(msg):
    print(msg.sender_id, msg.text)
```

A `Message` has `id`, `chat`, `sender_id`, `date` (UTC), `text`, `attachment`,
`from_me`, and shortcuts `reply`, `reply_file`, `edit`, `delete`, `react`,
`mark_seen`, `download`.

### Filters

| Filter | Matches |
|---|---|
| `F.private`, `F.group` | chat type |
| `F.text` | has text |
| `F.has_attachment` | has a file |
| `F.from_me` | sent by you |
| `F.from_user(1, 2)`, `F.in_chat(5)` | sender / chat ids |
| `F.text_equals("hi")`, `F.text_contains("a", "b")`, `F.text_matches(r"\d+")` | text (case-insensitive except regex) |
| `F.command("start", "help")` | `/start`, `/help x` (also `/start@name`) |

Combine with `&`, `|`, `~`: `F.private & ~F.command("stop")`. For the words
after a command: `F.command_args(msg)`.

### Streams and waiting

```python
async for msg in bale.messages(F.private):  # ends when the client stops
    ...

answer = await bale.wait_for(F.from_user(42), timeout=60)  # asyncio.TimeoutError
```

`wait_for` only sees messages that arrive after it starts listening.

### Errors in handlers

A handler that raises does not stop the others or the connection. Register
`@bale.on_error` to get `(exception, message)`; otherwise it is logged.

## Sending

The target can be a phone number, a chat id (`int`), a `Chat`, a `User` or a
`Message` (its chat).

```python
await bale.send_text("09121234567", "hi")
await bale.send_text(msg, "quoted", reply_to=msg)  # same as msg.reply("quoted")
await bale.send_file(chat, "report.pdf", caption="here")  # path, bytes or open binary file
await bale.send_photo(chat, open("a.jpg", "rb"))
await bale.send_file(chat, "v.ogg", kind=FileKind.VOICE)  # DOCUMENT PHOTO VIDEO VOICE AUDIO GIF
await sent.edit("new")
await sent.react("👍")
await sent.delete(just_me=True)
async with bale.typing(chat):  # shows "typing..."
    ...
await bale.mark_seen(chat)
```

Text over 4000 characters is split at paragraph, line or word boundaries
(`split=False` to disable). Sends go one at a time with `min_send_interval`
between them.

Unknown phone number -> `ChatNotFound`.

## Reading history

```python
recent = await bale.history(chat, 20)  # newest first
async for m in bale.iter_history(chat):  # the whole chat
    ...
async for m in bale.iter_history(chat, max_messages=500):
    ...
chats = await bale.dialogs()
user = await bale.get_user(chat)
await msg.download("saved.bin")  # or no path -> returns a file object
```

Bale returns about 40 messages per request; `iter_history` pages for you.

## Errors

All errors subclass `BaleError` and carry a stable `code` and a `message`:

| Class | `code` |
|---|---|
| `InvalidPhone` | `INVALID_PHONE` |
| `NotRegistered` | `PHONE_NOT_REGISTERED` |
| `NumberBanned` | `NUMBER_BANNED` |
| `RateLimited` | `RATE_LIMITED` |
| `CodeNotRequested` | `CODE_NOT_REQUESTED` |
| `WrongCode` | `WRONG_CODE` |
| `PasswordRequired` / `WrongPassword` | `PASSWORD_REQUIRED` / `WRONG_PASSWORD` |
| `NotLoggedIn` / `AlreadyLoggedIn` | `NOT_LOGGED_IN` / `ALREADY_LOGGED_IN` |
| `NotConnected` / `ConnectionFailed` | `NOT_CONNECTED` / `CONNECTION_FAILED` |
| `RequestFailed` | `REQUEST_FAILED` |
| `ChatNotFound` | `CHAT_NOT_FOUND` |
| `UnsupportedFile` | `UNSUPPORTED_FILE` |

Messages are written by this library; nothing Bale sends is copied into an error.

## Testing your code

```python
from balesdk import BaleClient
from balesdk.testing import FakeTransport


async def test_ping():
    fake = FakeTransport(logged_in=True)
    async with BaleClient("t", transport=fake, min_send_interval=0) as bale:
        bale.on_message()(lambda m: m.reply("pong"))
        await fake.deliver("hi", chat_id=42)
        await asyncio.sleep(0.05)
        assert fake.sent[-1].text == "pong"
```

`FakeTransport` records `sent`, `sent_files`, `edits`, `deleted`, `reactions`,
and can simulate a wrong code, a password (`password="x"`), a failed connection
(`fail_connect=True`) and a dropped link (`drop_connection()`).

## Being a good citizen

Bale can restrict accounts that behave like machines. Keep `min_send_interval`
above zero, do not message people who have not asked to hear from you, do not
send in large bursts, and use `bale.typing(...)` before replying. See
[SECURITY.md](../SECURITY.md).
