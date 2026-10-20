# balelink

Log in to [Bale](https://bale.ai) (بله) with your **personal account** - not a
bot - and send and receive messages from Python, from the command line, or over
HTTP. [فارسی](README.fa.md)

> **Unofficial, and it can get your account banned.** Bale's supported interface
> is the Bot API. This drives a normal user account through Bale's internal
> protocol. Read [SECURITY.md](SECURITY.md) before you use a number you care
> about. Not affiliated with Bale.

> **Status: alpha.** Tested against an in-memory fake and the signatures of the
> underlying library, and by hand on one live account: login with a code,
> reconnecting from the saved login, sending and receiving text, **photos, voice
> and locations**, downloading files, reading history, and read-only contact and
> chat calls. **Not yet tried live:** groups, contact changes, blocking,
> forwarding, pinning, edit/delete events, and the gateway. Run
> [`examples/smoke_test.py`](examples/smoke_test.py) and open an issue with the
> output if something fails.

```python
import asyncio
from balelink import BaleClient, filters as F

bale = BaleClient("me")


@bale.on_message(F.private & F.command("ping"))
async def ping(msg):
    await msg.reply("pong")


async def main():
    async with bale:  # reuses the saved login
        await bale.send_text("09121234567", "hello")  # by phone number
        await bale.run_forever()


asyncio.run(main())
```

## Install

```bash
pip install balelink                  # the library and CLI
pip install "balelink[gateway]"       # + the HTTP gateway
```

Python 3.9+. It is built on [aiobale](https://github.com/aminmadaniofficial/aiobale)
(MIT), which does the protocol work - see [NOTICE](NOTICE).

## Log in

The first time, ask Bale for a code and type what it sends you:

```python
bale = BaleClient("me")
await bale.login(
    "09121234567", code=lambda: input("code: "), password=lambda: input("two-step password: ")
)  # only if you set one
```

or `balelink login me`. The login is saved to `~/.balelink/me.bale` (set
`BALELINK_HOME` to move it); later runs need no code. **That file is your
account** - keep it private. Phone numbers may be written `0912...`, `+98 912...`
or in Persian digits.

Step by step instead: `await bale.request_code(phone)`, then
`await bale.sign_in(code, password=...)`.

## Receive

```python
@bale.on_message()                       # every incoming message
@bale.on_message(F.private & F.text)     # filters combine with & | ~
@bale.on_message(F.group & F.text_contains("help"))
@bale.on_message(F.command("start", "help"))
```

Filters: `private`, `group`, `text`, `from_me`, `has_attachment`,
`from_user(id)`, `in_chat(id)`, `text_equals`, `text_contains`, `text_matches`,
`command`. Handlers can be `async` or plain; one that raises does not stop the
others (`@bale.on_error` sees it). Your own messages are not delivered unless
you pass `deliver_own=True`.

Or consume a stream, or wait for one message:

```python
async for msg in bale.messages(F.private):
    ...
reply = await bale.wait_for(F.from_user(42), timeout=60)
```

`@bale.on_ready` and `@bale.on_disconnect` report the connection coming and
going; reconnecting is automatic.

## What it can do

Text, photos, voice, video, audio, files and **locations** - sending and receiving.
Edit, delete, reply, forward, pin, react (and un-react), typing, mark seen, history
(paged), chats. Contacts (check a number, add, rename, block). Groups (create, edit,
members, admins, invite links, join, leave). Your profile. Events for new, edited
and deleted messages and for the connection. Plus an HTTP gateway with webhooks
that mirrors [WAHA](https://waha.devlike.pro), and a CLI. Details in the
[guide](docs/guide.md) and [gateway docs](docs/gateway.md).

## Send

```python
await bale.send_text("09121234567", "hi")  # phone number, chat id, User, or Message
await bale.send_text(chat_id, long_text)  # >4000 characters is split for you
await msg.reply("quoted reply")
await bale.send_file(chat, "report.pdf", caption="here")
await bale.send_photo(chat, open("a.jpg", "rb"))
await bale.send_file(chat, voice_bytes, kind=FileKind.VOICE)
await sent.edit("new text")
await sent.react("👍")
await sent.delete()
async with bale.typing(msg):  # "typing..." while you work
    ...
await bale.history(chat, 20)
await bale.dialogs()
await msg.download("out.bin")
```

Sends are serialised with a small gap (`min_send_interval`, 0.4 s) so a burst
does not look like a script.

## Errors

Every error is a `BaleError` with a stable `.code` (`WRONG_CODE`,
`PASSWORD_REQUIRED`, `RATE_LIMITED`, `NUMBER_BANNED`, `CHAT_NOT_FOUND`,
`NOT_CONNECTED`, ...). Branch on the class or the code, never on the text; no
error carries text received from Bale.

## Command line

```bash
balelink login me
balelink send me 09121234567 "hello"
echo "from a pipe" | balelink send me 09121234567 -
balelink listen me
balelink sessions
balelink logout me          # also deletes the saved login
```

## HTTP gateway

Run accounts as a service so any language can use them, WAHA-style:

```bash
BALELINK_API_KEY=change-me balelink serve        # 127.0.0.1:8787
```

All calls (except `/health`) need `X-Api-Key`. Interactive docs at `/docs`.

| Call | |
|---|---|
| `POST /sessions` `{name, webhook_url?, webhook_secret?}` | add an account |
| `POST /sessions/{n}/login/code` `{phone}` then `/login/verify` `{code, password?}` | sign in |
| `POST /sessions/{n}/messages` `{to, text, reply_to?}` | send (`chat_id: true` if `to` is a chat id) |
| `POST /sessions/{n}/files` `{to, data(base64), kind, caption?}` | send a file |
| `PATCH` / `DELETE /sessions/{n}/messages/{id}` | edit / delete |
| `POST /sessions/{n}/messages/{id}/reaction` `{emoji}` | react |
| `GET /sessions/{n}/chats/{chat}/messages?limit=` | history |
| `PUT /sessions/{n}/webhook` `{url, secret}` | where to send incoming messages |
| `GET /sessions` `/sessions/{n}` `POST .../start` `.../stop` `DELETE /sessions/{n}` | manage |

Incoming messages are POSTed to the webhook as
`{"event": "message", "session": "me", "message": {...}}`, signed with
HMAC-SHA256 in `X-Balelink-Signature` when you set a secret, retried with
backoff, and never allowed to block the connection. Errors are
`{"error": {"code", "message"}}`. Sessions and webhooks are saved, and accounts
reconnect when the gateway restarts. Settings: `BALELINK_HOST`, `_PORT`,
`_API_KEY`, `_HOME`, `_AUTOSTART`, `_WEBHOOK_ATTEMPTS`, `_WEBHOOK_TIMEOUT`.

## Testing your own bot

```python
from balelink import BaleClient
from balelink.testing import FakeTransport

fake = FakeTransport(logged_in=True)
async with BaleClient("t", transport=fake) as bale:
    ...
    await fake.deliver("/ping", chat_id=42)
    assert fake.sent[-1].text == "pong"
```

## How it is built

`BaleClient` talks to a small `Transport` protocol; `balelink/_aiobale.py` is
the only file that imports aiobale. When Bale or aiobale changes, that one file
changes. A contract test checks the adapter against the installed aiobale.

## Documentation

[Getting started](docs/getting-started.md) ·
[Guide](docs/guide.md) ·
[HTTP gateway](docs/gateway.md) ·
[Troubleshooting & FAQ](docs/troubleshooting.md) ·
[Publishing](docs/PUBLISHING.md) · [Security](SECURITY.md)

## Limits

Personal chats and groups only (no channels or calls). Message formatting
(bold, links) and inline buttons are not exposed yet. Two-step login and file
types follow what aiobale supports.

MIT licensed. See [CONTRIBUTING.md](CONTRIBUTING.md).
