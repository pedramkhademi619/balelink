"""A small auto-reply bot that runs on your own account.

python examples/02_auto_reply.py
"""

import asyncio

from balelink import BaleClient
from balelink import filters as F

bale = BaleClient("me")


@bale.on_message(F.private & F.command("ping"))
async def ping(msg):
    await msg.reply("pong")


@bale.on_message(F.private & F.text_contains("hello", "سلام"))
async def greet(msg):
    async with bale.typing(msg):
        await asyncio.sleep(1)  # look human; Bale may restrict accounts that act like machines
    await msg.reply("Hi! I'll get back to you soon.")


@bale.on_error
def log_errors(exc, msg):
    print(f"handler failed on message {msg.id}: {exc!r}")


async def main() -> None:
    async with bale:
        print("Running - Ctrl-C to stop.")
        await bale.run_forever()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
