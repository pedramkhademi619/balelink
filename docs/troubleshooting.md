# Troubleshooting and FAQ

**I get `RATE_LIMITED` when asking for a code.** Bale limits code requests per
number. Wait a while and try once, not repeatedly.

**`WRONG_CODE`.** Codes expire in about a minute, and a new request invalidates
the old code. Use the newest one.

**`PASSWORD_REQUIRED`.** The account has a two-step password. Pass
`password=` (or a function) to `login` / `sign_in`.

**`NUMBER_BANNED`.** Bale has blocked the number. Nothing in this library can
change that.

**`CHAT_NOT_FOUND` when sending to a number.** The number is not a Bale user,
or is not in a form Bale knows. `0912...`, `+98912...` and `98912...` are all
accepted.

**`NOT_CONNECTED`.** The client is not started, or the link dropped. Use
`async with bale:` / `await bale.start()`, and `await bale.wait_until_connected()`
before the first send in a short script.

**`CONNECTION_FAILED` / `last_error()`.** Bale (`web.bale.ai`) could not be
reached. Some networks block it; try another network or a proxy.

**It worked yesterday and now nothing does.** Bale changed its internal
protocol. Update (`pip install -U balesdk aiobale-py`) and open an issue.

**Where is my login?** `~/.balesdk/<name>.bale` (or `$BALESDK_HOME`).
Delete the file, or run `balesdk logout <name>`, to forget it.

**Can I use two accounts?** Yes: `BaleClient("work")` and `BaleClient("home")`,
each with its own login.

**Can I run this on a server with no one to type the code?** Log in once on a
machine where you can, then copy the `.bale` file (securely, mode 600) to the
server. Or use the gateway and send the code through its API.

**Does it work with groups and channels?** Private chats and groups. Channels
are not exposed.

**Can it send formatted text, buttons, stickers?** Not yet.

**Is this allowed by Bale?** Bale's supported route is the Bot API. Driving a
personal account is unofficial and may break their terms; accounts can be
restricted. Read [SECURITY.md](../SECURITY.md). If you only need a bot, use the
official API instead.

**Debug logs.** `balesdk -v ...` on the command line, or
`logging.basicConfig(level=logging.DEBUG)` in code. balesdk's own log lines never
include codes or passwords, but the underlying `aiobale` logger (and DEBUG output
in general) may include more - read logs before pasting them in an issue, and
remove phone numbers and ids.
