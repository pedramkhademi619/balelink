# Getting started

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install balesdk                                  # library + command line
pip install "balesdk[gateway]"                       # also the HTTP gateway
```

Python 3.9 or newer. Check it works:

```bash
balesdk --version
```

## 2. Log in (once)

```bash
balesdk login me
```

It asks for your phone number (`0912...`, `+98 912...`, Persian digits all work),
Bale sends you a code, you type it, and - only if you set a
two-step password - that too. The login is saved as `~/.balesdk/me.bale`.
`me` is just a name; use another name for a second account.

> That file **is** your account: whoever has it can read your chats and send as
> you. It is created readable by you only. Never commit or share it.

## 3. Send a message

```bash
balesdk send me 09121234567 "hello"
```

The recipient must be a Bale user whose number you can look up. For a group or a
chat you already have the id of, add `--chat-id` and pass the id.

## 4. See incoming messages

```bash
balesdk listen me
```

## 5. Write a program

```python
import asyncio
from balesdk import BaleClient, filters as F

bale = BaleClient("me")  # uses the login from step 2


@bale.on_message(F.private & F.command("ping"))
async def ping(msg):
    await msg.reply("pong")


async def main():
    async with bale:
        await bale.send_text("09121234567", "I'm online")
        await bale.run_forever()  # Ctrl-C to stop


asyncio.run(main())
```

Next: [the guide](guide.md), [the HTTP gateway](gateway.md),
[troubleshooting](troubleshooting.md).
