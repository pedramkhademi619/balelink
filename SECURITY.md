# Security and responsible use

## What a saved login is

`~/.balesdk/<name>.bale` **is your account**. Whoever holds the file can read
your chats and send as you, with no code and no password. balesdk creates the
directory `0700` and the files `0600`; keep it that way and never commit,
upload, or share it. Back it up like a password.

## Terms of service - you carry the risk

This is an **unofficial** client of Bale's internal protocol. Bale's official
interface is the Bot API (<https://docs.bale.ai>); a personal account is not
meant to be driven by software. Using this may breach Bale's terms and can get
the account **restricted or banned**, and Bale can change its protocol at any
time and break this library without notice. Use a number you can afford to
lose, keep message rates low, and do not use it for spam, scraping, or
contacting people who have not asked to hear from you. The authors accept no
responsibility for what happens to your account.

## The gateway

- It listens on `127.0.0.1` by default. `balesdk serve` refuses to bind a
  non-local address without `BALESDK_API_KEY`.
- Put it behind HTTPS (a reverse proxy) before exposing it - the API key and
  your messages travel in the clear otherwise.
- Webhook URLs are fetched by the server. Anyone with the API key can make it
  call any URL it can reach, so treat the key like a password.
- Set a webhook `secret` and verify `X-Balesdk-Signature` on the receiving end
  (see `examples/05_webhook_receiver.py`).

## Reporting a vulnerability

Open a private security advisory on the repository (not a public issue).
