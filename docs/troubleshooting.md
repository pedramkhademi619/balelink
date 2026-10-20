# Troubleshooting and FAQ

**I get `RATE_LIMITED` when asking for a code.** Bale limits code requests per
number. Wait a while and try once, not repeatedly.

**`WRONG_CODE`.** Codes expire in about a minute, and a new request invalidates
the old code. Use the newest one.

**`PASSWORD_REQUIRED`.** The account has a two-step password. Pass
`password=` (or a function) to `login` / `sign_in`.

**`NUMBER_BANNED`.** Bale has blocked the number. Nothing in this library can
change that.

**Phone lookups start answering "not found" for numbers that exist.** Bale
throttles phone-number searches: in testing, the first couple worked and the rest
of a quick series returned nothing, even for the account's own number. balelink
remembers every number it resolves in `~/.balelink/<session>.phones.json`, so a
number costs one lookup ever. Replying to someone who wrote to you needs no lookup
at all (use `msg.reply(...)`, or the chat id). Wait a while before retrying
lookups; `bale.remember_phone(phone, user_id)` lets you add a known id by hand.

**`CHAT_NOT_FOUND` when sending to a number.** The number is not a Bale user,
or is not in a form Bale knows. `0912...`, `+98912...` and `98912...` are all
accepted.

**`NOT_CONNECTED`.** The client is not started, or the link dropped. Use
`async with bale:` / `await bale.start()`, and `await bale.wait_until_connected()`
before the first send in a short script.

**`CONNECTION_FAILED` / `last_error()`.** Bale (`web.bale.ai`) could not be
reached. Some networks block it; try another network or a proxy.

**It worked yesterday and now nothing does.** Bale changed its internal
protocol. Update (`pip install -U balelink aiobale-py`) and open an issue.

**Where is my login?** `~/.balelink/<name>.bale` (or `$BALELINK_HOME`).
Delete the file, or run `balelink logout <name>`, to forget it.

**Can I use two accounts?** Yes: `BaleClient("work")` and `BaleClient("home")`,
each with its own login.

**Can I run this on a server with no one to type the code?** Log in once on a
machine where you can, then copy the `.bale` file (securely, mode 600) to the
server. Or use the gateway and send the code through its API.

**Does it work with groups and channels?** Private chats and groups. Channels
are not exposed.

**Can it send formatted text, buttons, stickers, polls?** Not yet.

**Can it send photos, voice and locations?** Yes - see the guide. Files go through
Bale's upload service; the first live tests of each are noted in the changelog.

**Is this allowed by Bale?** Bale's supported route is the Bot API. Driving a
personal account is unofficial and may break their terms; accounts can be
restricted. Read [SECURITY.md](../SECURITY.md). If you only need a bot, use the
official API instead.

**Debug logs.** `balelink -v ...` on the command line, or
`logging.basicConfig(level=logging.DEBUG)` in code. balelink's own log lines never
include codes or passwords, but the underlying `aiobale` logger (and DEBUG output
in general) may include more - read logs before pasting them in an issue, and
remove phone numbers and ids.
