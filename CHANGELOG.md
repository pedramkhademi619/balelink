# Changelog

## 0.1.0

First release. Log in with a phone number (code and optional two-step
password), send and receive text and files, edit, delete, react, typing, history,
filters, `async for` streams, an HTTP gateway with webhooks, and a CLI.

`history(before=)` and `iter_history()` page through a whole chat.

Verified with an in-memory fake transport and by checking every aiobale call
against the installed library. Checked by hand against one live account: login with a code, connecting,
reusing the saved login, sending a text, and reading history. Receiving, files,
edit/delete/react and the gateway have not been tried live.
