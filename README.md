<div align="center">

# balelink

**Log in to [Bale](https://bale.ai) with your own account, then send and receive messages from Python, the command line, or plain HTTP.**

[![PyPI](https://img.shields.io/pypi/v/balelink?color=2b7de9)](https://pypi.org/project/balelink/)
[![Python](https://img.shields.io/pypi/pyversions/balelink)](https://pypi.org/project/balelink/)
[![CI](https://github.com/pedramkhademi619/balelink/actions/workflows/ci.yml/badge.svg)](https://github.com/pedramkhademi619/balelink/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[Getting started](docs/getting-started.md) &nbsp;·&nbsp; [Guide](docs/guide.md) &nbsp;·&nbsp; [HTTP gateway](docs/gateway.md) &nbsp;·&nbsp; [FAQ](docs/troubleshooting.md) &nbsp;·&nbsp; [فارسی](README.fa.md)

</div>

> [!WARNING]
> **Unofficial.** This drives a normal user account through Bale's internal protocol, which can get the account restricted or banned. Bale's supported interface is the Bot API. Read [SECURITY.md](SECURITY.md) before using a number you care about. Not affiliated with Bale.

```python
import asyncio
from balelink import BaleClient, filters as F

bale = BaleClient("me")

@bale.on_message(F.private & F.command("ping"))
async def ping(msg):
    await msg.reply("pong")

async def main():
    async with bale:                                   # reuses the saved login
        await bale.send_text("09121234567", "hello")   # by phone number
        await bale.run_forever()

asyncio.run(main())
```

## Features

| Area | What you get |
|---|---|
| **Messages** | text, photos, voice, video, audio, files, **locations**; reply, edit, delete, forward, pin, react, typing, seen |
| **Receiving** | handlers with composable filters, `async for` streams, `wait_for`; new, edited and deleted messages; connection events |
| **Chats** | history (paged through the whole chat), recent chats, clear and delete |
| **Contacts** | check a number, add, rename, block and unblock, user info |
| **Groups** | create, edit, members, admins, invite links, join, leave |
| **Login** | phone and code, optional two-step password, saved and reused |
| **Gateway** | an HTTP service in the style of [WAHA](https://waha.devlike.pro): sessions, webhooks with event filters and signatures, send by URL, media download |
| **Tooling** | CLI (`balelink login / send / listen / serve`), `FakeTransport` for testing bots offline, stable error codes |

## Install

```bash
pip install balelink                 # library and CLI
pip install "balelink[gateway]"      # plus the HTTP gateway
```

Python 3.9 or newer. Built on [aiobale](https://github.com/aminmadaniofficial/aiobale) (MIT), which does the protocol work. See [NOTICE](NOTICE).

## Log in

```bash
balelink login me
```

It asks for your phone number, Bale sends a code, you type it (and your two-step password, if you set one). The login is saved to `~/.balelink/me.bale` and later runs need no code.

> [!IMPORTANT]
> That file **is** your account. Whoever has it can read your chats and send as you. Keep it private and never commit it.

From code:

```python
await bale.login("09121234567",
                 code=lambda: input("code: "),
                 password=lambda: input("two-step password: "))   # only asked if needed
```

Numbers can be written `0912...`, `+98 912...` or in Persian digits.

## Receive

```python
@bale.on_message(F.private & F.text)               # filters combine with & | ~
@bale.on_message(F.group & F.text_contains("help"))
@bale.on_message(F.command("start", "help"))
@bale.on_message(F.photo)                          # also F.voice, F.video, F.location, ...
@bale.on_edited(F.private)
```

Handlers can be `async` or plain functions; one that raises does not stop the others. Your own messages are not delivered unless you pass `deliver_own=True`.

```python
async for msg in bale.messages(F.private):         # a stream
    ...
reply = await bale.wait_for(F.from_user(42), timeout=60)
```

## Send

```python
await bale.send_text("09121234567", "hi")          # phone number, chat id, User or Message
await msg.reply("quoted reply")
await bale.send_photo(chat, "pic.jpg", caption="look")
await bale.send_file(chat, "note.ogg", kind=FileKind.VOICE)
await bale.send_location(chat, 35.7, 51.4)
await sent.edit("new text"); await sent.react("👍"); await sent.delete()
async with bale.typing(msg):                       # shows "typing..." while you work
    ...
async for m in bale.iter_history(chat): ...        # the whole chat, newest first
```

Text over 4000 characters is split for you, and sends keep a small gap (`min_send_interval`) so a burst does not look like a script.

## Command line

```bash
balelink login me
balelink send me 09121234567 "hello"
balelink listen me
balelink serve                  # the HTTP gateway
```

## HTTP gateway

```bash
BALELINK_API_KEY=change-me balelink serve        # http://127.0.0.1:8787
```

Sessions, login, sending, contacts, groups, and **webhooks** for incoming events, all over HTTP. Interactive docs are at `/docs`. See the [gateway guide](docs/gateway.md).

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

## Status

Alpha. Checked by hand on one live account:

| Works live | Not yet tried live |
|---|---|
| login with a code, reconnecting from the saved login | groups |
| sending and receiving text, **photos, voice, locations** | contact changes, blocking |
| downloading files, reading history | forwarding, pinning |
| contacts, block list and chat list (read-only) | edit/delete events, the HTTP gateway |

Everything is also covered by 150+ offline tests. Run [`examples/smoke_test.py`](examples/smoke_test.py) on your own account and open an issue with the output if something fails.

## How it is built

`BaleClient` talks to a small `Transport` protocol, and [`balelink/_aiobale.py`](balelink/_aiobale.py) is the only file that imports aiobale. When Bale or aiobale changes, that one file changes. A contract test checks it against the installed aiobale.

## Limits

Private chats and groups only (no channels or calls). Formatted text, buttons and polls are not exposed yet. Bale throttles phone-number lookups, so balelink remembers every number it resolves (see the [FAQ](docs/troubleshooting.md)).

---

MIT licensed. [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md)
