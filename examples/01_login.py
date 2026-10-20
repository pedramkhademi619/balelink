"""Log in once; the login is saved and later scripts reuse it.

python examples/01_login.py
"""

import asyncio

from balesdk import BaleClient, BaleError


async def main() -> None:
    bale = BaleClient("me")
    if bale.is_logged_in:
        print("Already logged in.")
        return
    try:
        me = await bale.login(
            input("Phone (0912...): "),
            code=lambda: input("Code Bale sent: "),
            password=lambda: input("Two-step password: "),
        )
    except BaleError as e:
        print(f"Failed: {e.code} - {e.message}")
        return
    print(f"Logged in as {me.id}")


asyncio.run(main())
