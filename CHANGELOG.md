# Changelog

## Unreleased

- Photos, voice and **locations**: send and receive, with size/duration/caption on
  `Attachment` and `Message.location`. Filters `F.photo`, `F.voice`, `F.video`,
  `F.audio`, `F.document`, `F.location`.
- Edit/delete events (`on_edited`, `on_deleted`), `on_event`, forwarding, pinning,
  un-react, delete/clear chat.
- Contacts (check, add, remove, rename, block), groups (create, edit, members,
  admins, invite links, join, leave), profile.
- Gateway: several webhooks per session with event filters, custom headers and
  per-webhook retries; `session.status`, `message.any`, `message.edited`,
  `message.revoked` events; send by URL (with an SSRF guard); media download;
  contacts, groups, profile, forward, pin, typing and location endpoints;
  `restart`, `logout`, `me`, per-session `ignore` rules and metadata.
  **The webhook body is now an envelope** `{id, timestamp, event, session, me, payload}`.
- Phone-number lookups are cached on disk (Bale throttles them).

Checked live on one account: photo, voice and location received and downloaded;
location, photo (with caption and size) and voice sent to the account's own chat;
read-only contact, block-list and dialog calls. Groups, contact changes, blocking,
forwarding, pinning, edits/deletes events and the whole gateway have only been
exercised against the in-memory fake.

## 0.1.0

First release. Log in with a phone number (code and optional two-step
password), send and receive text and files, edit, delete, react, typing, history,
filters, `async for` streams, an HTTP gateway with webhooks, and a CLI.

`history(before=)` and `iter_history()` page through a whole chat.

Verified with an in-memory fake transport and by checking every aiobale call
against the installed library. Checked by hand against one live account: login with a code, connecting,
reusing the saved login, sending a text, and reading history. Receiving, files,
edit/delete/react and the gateway have not been tried live.
