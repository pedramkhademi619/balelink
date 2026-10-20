"""Check the library works with YOUR real account. Run this first.

    python examples/smoke_test.py

It logs in (or reuses a saved login), connects, and - only if you give a phone
number - sends one message to it and waits for you to reply. Nothing is sent
without your say-so. Report what it prints if something fails; that output is
the most useful thing for fixing a problem.
"""

import asyncio
import logging

from balesdk import BaleClient, BaleError

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    bale = BaleClient("smoke")
    if not bale.is_logged_in:
        phone = input("Your Bale phone number: ")
        await bale.login(
            phone,
            code=lambda: input("Code Bale sent: "),
            password=lambda: input("2-step password: "),
        )
        print("1/4 login ........ ok")
    else:
        print("1/4 login ........ reusing saved login")

    await bale.start()
    if not await bale.wait_until_connected(30):
        print("2/4 connect ...... FAILED:", bale.last_error())
        return
    print("2/4 connect ...... ok, id =", bale.me.id if bale.me else "?")

    target = input("Phone to send a test message to (empty = skip): ").strip()
    if target:
        sent = await bale.send_text(target, "balesdk smoke test - reply to this message")
        print("3/4 send ......... ok, message", sent.id)
        print("4/4 receive ...... reply to it from that account within 60 s ...")
        try:
            got = await bale.wait_for(timeout=60)
            print("4/4 receive ...... ok:", got.text)
        except asyncio.TimeoutError:
            print("4/4 receive ...... nothing arrived (not necessarily a bug)")
    await bale.stop()


try:
    asyncio.run(main())
except BaleError as e:
    print(f"FAILED: {e.code} - {e.message}")
