"""Receive photos, voices and locations; answer with a location and a photo.

python examples/06_media_and_location.py
"""

import asyncio
import pathlib

from balelink import BaleClient
from balelink import filters as F

bale = BaleClient("me")
DOWNLOADS = pathlib.Path("downloads")
DOWNLOADS.mkdir(exist_ok=True)


@bale.on_message(F.private & F.photo)
async def got_photo(msg):
    a = msg.attachment
    path = DOWNLOADS / f"{msg.id}_{a.name or 'photo.jpg'}"
    await msg.download(path)
    await msg.reply(f"Saved your {a.width}x{a.height} photo ({a.size} bytes).")


@bale.on_message(F.private & F.voice)
async def got_voice(msg):
    await msg.download(DOWNLOADS / f"{msg.id}.ogg")
    await msg.reply(f"Got a {msg.attachment.duration_ms / 1000:.1f}s voice note.")


@bale.on_message(F.private & F.location)
async def got_location(msg):
    loc = msg.location
    await msg.reply(f"You are at {loc.latitude:.4f}, {loc.longitude:.4f}\n{loc.maps_url}")
    await msg.reply_location(loc.latitude, loc.longitude)  # send it straight back


async def main():
    async with bale:
        print("Send me a photo, a voice note or a location. Ctrl-C to stop.")
        await bale.run_forever()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    pass
