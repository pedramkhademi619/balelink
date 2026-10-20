"""``balelink`` on the command line.

balelink login me            sign in (asks for phone, code, password)
balelink whoami me
balelink send me 09121234567 "hello"
balelink listen me           print incoming messages until Ctrl-C
balelink sessions
balelink logout me
balelink serve               the HTTP gateway (pip install "balelink[gateway]")
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from typing import List, Optional

from . import __version__
from .client import BaleClient
from .errors import BaleError
from .store import SessionStore


def _client(args: argparse.Namespace) -> BaleClient:
    return BaleClient(args.session, directory=args.directory)


async def _login(args: argparse.Namespace) -> int:
    client = _client(args)
    if client.is_logged_in and not args.force:
        print(f"'{args.session}' is already logged in. Use --force to log in again.")
        return 0
    phone = args.phone or input("Phone number (0912... or +98...): ").strip()
    me = await client.login(
        phone,
        code=lambda: input("Code Bale sent you: "),
        password=lambda: getpass.getpass("Two-step password: "),
    )
    print(f"Logged in as {me.id}. Saved as '{args.session}' in {client.store.directory}")
    print("That file is your login - keep it private.")
    return 0


async def _whoami(args: argparse.Namespace) -> int:
    async with _client(args) as client:
        if not client.is_logged_in:
            print("Not logged in.")
            return 1
        await client.wait_until_connected(20)
        me = client.me
        print(f"id={me.id if me else '?'} connected={client.is_connected}")
        return 0 if client.is_connected else 2


async def _send(args: argparse.Namespace) -> int:
    async with _client(args) as client:
        if not await client.wait_until_connected(30):
            print("Could not connect.", file=sys.stderr)
            return 2
        target = int(args.to) if args.chat_id else args.to
        text = args.text if args.text != "-" else sys.stdin.read()
        sent = await client.send_text(target, text)
        print(f"sent (message {sent.id})")
        return 0


async def _listen(args: argparse.Namespace) -> int:
    async with _client(args) as client:
        if not client.is_logged_in:
            print("Not logged in.")
            return 1
        print("Listening - Ctrl-C to stop.")
        async for m in client.messages():
            who = f"{m.chat.kind.value}:{m.chat.id}"
            print(f"[{m.date:%H:%M:%S}] {who} <{m.sender_id}> {m.text or '[attachment]'}")
    return 0


async def _logout(args: argparse.Namespace) -> int:
    client = _client(args)
    if not client.is_logged_in:
        print("Not logged in.")
        return 0
    await client.logout()
    print("Logged out and the saved login was deleted.")
    return 0


def _sessions(args: argparse.Namespace) -> int:
    names = SessionStore(args.directory).names()
    print("\n".join(names) if names else "(no saved logins)")
    return 0


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from .gateway import Settings, create_app
    except ImportError:
        print('The gateway needs extra packages: pip install "balelink[gateway]"', file=sys.stderr)
        return 1
    base = Settings.from_env()
    settings = Settings(
        host=args.host or base.host,
        port=args.port or base.port,
        api_key=base.api_key,
        directory=args.directory or base.directory,
        autostart=base.autostart,
        webhook_timeout=base.webhook_timeout,
        webhook_attempts=base.webhook_attempts,
    )
    if not settings.api_key and settings.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "Refusing to listen on a non-local address without BALELINK_API_KEY: "
            "anyone who could reach it would control your Bale accounts.",
            file=sys.stderr,
        )
        return 1
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="balelink", description="Bale personal-account client.")
    p.add_argument("--version", action="version", version=f"balelink {__version__}")
    p.add_argument("--directory", help="where logins are kept (default ~/.balelink)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def with_session(name: str, help_: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("session", help="a name for this login, e.g. 'me'")
        return sp

    lg = with_session("login", "sign in with a phone number")
    lg.add_argument("--phone")
    lg.add_argument("--force", action="store_true")
    with_session("logout", "sign out and delete the saved login")
    with_session("whoami", "check the saved login connects")
    snd = with_session("send", "send a text message")
    snd.add_argument("to", help="a phone number (or a chat id with --chat-id)")
    snd.add_argument("text", help="the message, or - to read it from stdin")
    snd.add_argument("--chat-id", action="store_true")
    with_session("listen", "print incoming messages")
    sub.add_parser("sessions", help="list saved logins")
    sv = sub.add_parser("serve", help="run the HTTP gateway")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if args.command == "sessions":
        return _sessions(args)
    if args.command == "serve":
        return _serve(args)
    run = {
        "login": _login,
        "logout": _logout,
        "whoami": _whoami,
        "send": _send,
        "listen": _listen,
    }[args.command]
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except BaleError as e:
        print(f"{e.code}: {e.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
