"""Send a text and a file to a phone number.

python examples/03_send.py 09121234567 "hello"
"""

import asyncio
import sys

from balesdk import BaleClient, FileKind


async def main(phone: str, text: str) -> None:
    async with BaleClient("me") as bale:
        await bale.wait_until_connected()
        await bale.send_text(phone, text)
        await bale.send_file(
            phone, b"hello from balesdk", kind=FileKind.DOCUMENT, file_name="hi.txt"
        )
        print("sent")


asyncio.run(main(sys.argv[1], sys.argv[2]))
