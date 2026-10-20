# HTTP gateway

Run Bale accounts as a service so any language can use them: sessions, webhooks
for incoming events, an API key, send-by-URL, contacts, groups. It follows the
shape of [WAHA](https://waha.devlike.pro) (the WhatsApp HTTP API) where Bale has
an equivalent.

```bash
pip install "balelink[gateway]"
BALELINK_API_KEY=change-me balelink serve        # http://127.0.0.1:8787
```

Interactive API docs: `http://127.0.0.1:8787/docs`. Every call except `/health`
and `/ping` needs the header `X-Api-Key: change-me`.

## Settings (environment)

| Variable | Default | |
|---|---|---|
| `BALELINK_API_KEY` | none | required header value. Without it only `127.0.0.1` is allowed. |
| `BALELINK_HOST` / `BALELINK_PORT` | `127.0.0.1` / `8787` | where to listen |
| `BALELINK_HOME` | `~/.balelink` | logins and `gateway.json` |
| `BALELINK_AUTOSTART` | `true` | reconnect every saved login at startup |
| `BALELINK_PUBLIC_URL` | none | this gateway's address as receivers see it; used for `media.url` in webhooks |
| `BALELINK_WEBHOOK_ATTEMPTS` | `4` | default tries per event (waits 1 s, 3 s, 9 s) |
| `BALELINK_WEBHOOK_TIMEOUT` | `10` | seconds per try |
| `BALELINK_ALLOW_PRIVATE_URLS` | `false` | let `url` file sources point at private/loopback addresses |

## Walkthrough

```bash
H='X-Api-Key: change-me'; B=http://127.0.0.1:8787; J='content-type: application/json'

curl -H "$H" -H "$J" $B/sessions -d '{
  "name": "me",
  "webhooks": [{"url": "https://example.com/hook", "events": ["message", "session.status"],
                "secret": "s3cret", "headers": {"X-Token": "abc"}, "retries": 5}],
  "ignore_groups": true
}'

curl -H "$H" -H "$J" $B/sessions/me/login/code   -d '{"phone":"09121234567"}'
curl -H "$H" -H "$J" $B/sessions/me/login/verify -d '{"code":"12345"}'
# a two-step account answers 401 PASSWORD_REQUIRED: repeat with "password":"..."

curl -H "$H" -H "$J" $B/sessions/me/messages -d '{"to":"09121234567","text":"hello"}'
curl -H "$H" -H "$J" $B/sessions/me/images   -d '{"to":"09121234567","url":"https://example.com/a.jpg","caption":"look"}'
curl -H "$H" -H "$J" $B/sessions/me/location -d '{"to":"09121234567","latitude":35.7,"longitude":51.4}'
```

## Endpoints

All paths start with `/sessions/{name}`.

**Sessions**

| | |
|---|---|
| `GET /sessions`, `POST /sessions`, `GET`/`DELETE /sessions/{name}` | manage accounts (`DELETE` logs out and removes it) |
| `POST .../start`, `/stop`, `/restart` | connect / disconnect / reconnect |
| `POST .../logout` | sign out of Bale but keep the session and its webhooks |
| `GET .../me` | the signed-in account |
| `POST .../login/code` `{phone}`, `.../login/verify` `{code, password?}` | sign in |
| `PUT .../webhook` `{url, secret, events}` | one webhook (`url: null` removes all) |
| `PUT .../webhooks` `{webhooks: [{url, events, secret, headers, retries}]}` | several webhooks |
| `PUT .../config` `{ignore_groups, ignore_private, metadata}` | per-session options |

**Sending** (`to` is a phone number; set `"chat_id": true` to pass a chat id)

| | |
|---|---|
| `POST .../messages` `{to, text, reply_to?}` | text (over 4000 characters is split) |
| `POST .../files`, `/images`, `/voice`, `/videos` `{to, data \| url, kind?, caption?, file_name?, reply_to?}` | `data` is base64, `url` is fetched by the gateway; up to 50 MB. `kind` is guessed from the type when you use `/files`. |
| `POST .../location` `{to, latitude, longitude, reply_to?}` | a map point |
| `POST .../typing` `{to, typing}` | typing indicator on/off |
| `POST .../forward` `{to, message_ids}` | forward recent messages |

**Message actions** (`{id}` is a message from the last 500 this session sent or saw)

| | |
|---|---|
| `PATCH .../messages/{id}` `{text}` | edit |
| `DELETE .../messages/{id}?just_me=` | delete |
| `POST`/`DELETE .../messages/{id}/reaction` `{emoji}` / `?emoji=` | react / remove reaction |
| `POST`/`DELETE .../messages/{id}/pin` `{just_me?}` | pin / unpin |
| `GET .../messages/{id}/media` | download the photo, voice, video or file |

**Chats**

| | |
|---|---|
| `GET .../chats` | your recent chats |
| `GET .../chats/{chat}/messages?limit=&before=` | history, newest first; `before` is a Unix timestamp for paging back |
| `POST .../chats/{chat}/seen`, `/clear` | mark read / clear |
| `DELETE .../chats/{chat}` | delete the chat |

**Contacts**

| | |
|---|---|
| `GET .../contacts` | your contacts |
| `GET .../contacts/check-exists?phone=` | is this number on Bale |
| `GET .../contacts/{id}` | name, username, about, contact/blocked flags |
| `POST .../contacts` `{user}` / `DELETE`/`PUT .../contacts/{id}` `{name}` | add / remove / rename |
| `POST .../contacts/{id}/block`, `/unblock`, `GET .../contacts/blocked` | blocking |

**Groups**

| | |
|---|---|
| `POST .../groups` `{title, members}` | create (members are phone numbers or user ids) |
| `GET`/`PUT .../groups/{id}` `{title?, about?}` | info / edit |
| `GET`/`POST .../groups/{id}/members` `{members}`, `DELETE .../members/{user}` | list / add / remove |
| `POST`/`DELETE .../groups/{id}/admins/{user}` | promote / demote |
| `GET .../groups/{id}/invite-link`, `POST .../invite-link/revoke` | invite link |
| `POST .../groups/join` `{link}`, `POST .../groups/{id}/leave` | join / leave |

**Profile**: `PUT .../profile` `{name?, about?, username?}`.

**Service**: `GET /health`, `GET /ping`, `GET /version`.

A user id is at most 10 digits; a leading `0` or `+`, or 11+ digits, means a phone
number.

## Errors

Always `{"error": {"code": "WRONG_CODE", "message": "..."}}`. Branch on `code`.
Status mapping: bad input 400/422, wrong password or API key 401, banned 403, not
found 404, state conflict 409, rate limit 429, Bale unreachable or unreadable 502.

## Webhooks

Every webhook gets this envelope:

```json
{
  "id": "5e1f...",
  "timestamp": 1790000160000,
  "event": "message",
  "session": "me",
  "me": {"id": 394131744, "phone": "989917888549"},
  "payload": { ... }
}
```

| Event | When | `payload` |
|---|---|---|
| `message` | a message from someone else | the message |
| `message.any` | any message, including your own from other devices | the message |
| `message.edited` | a message was edited | the message, as it is now |
| `message.revoked` | messages were deleted | `{chat: {id, kind}, ids: [...]}` |
| `session.status` | connected, disconnected, logged out, code sent... | `{status}` (`working`, `reconnecting`, `stopped`, `logged_out`, `code_sent`, `failed`) |

`events` defaults to `["message"]`; use `["*"]` for everything. A message:

```json
{
  "id": 1330336534499548412,
  "chat": {"id": 1805116387, "kind": "private"},
  "sender_id": 1805116387, "from_me": false,
  "date": "2026-10-20T14:10:35+00:00", "timestamp": 1790000000.0,
  "kind": "photo", "text": null, "caption": "look",
  "has_media": true,
  "media": {"kind": "photo", "name": "a.jpg", "mime_type": "image/jpeg", "size": 52249,
            "width": 540, "height": 1170, "duration_ms": null,
            "url": "https://gw.example.com/sessions/me/messages/1330.../media"},
  "location": null
}
```

`kind` is `text`, `photo`, `voice`, `video`, `audio`, `gif`, `document`,
`location` or `other`. For a location, `location` holds `latitude`, `longitude`
and a `maps_url`. `media.url` needs `BALELINK_PUBLIC_URL` and the `X-Api-Key`
header to fetch.

With a webhook `secret`, `X-Balelink-Signature: sha256=<hex>` is the HMAC-SHA256
of the raw body; verify it before trusting the request:

```python
import hmac, hashlib


def valid(secret: str, body: bytes, header: str) -> bool:
    mine = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mine, header)
```

Any 2xx is success; anything else is retried (`retries`, default 4, waiting 1 s,
3 s, 9 s), then dropped and logged. A webhook never delays receiving more
messages. Header values you set are never shown back by the API, only their names.

`ignore_groups` / `ignore_private` stop message webhooks for that kind of chat.

## Safety

- `url` sources are fetched by the gateway. It refuses non-http(s) URLs and
  private, loopback and link-local addresses, does not follow redirects, and
  stops at 50 MB.
- Put the gateway behind HTTPS. The API key and your messages are otherwise in
  the clear.
- Keep `BALELINK_HOME` on a private disk and back it up: it holds the logins.

## Docker

```dockerfile
FROM python:3.12-slim
RUN pip install "balelink[gateway]"
ENV BALELINK_HOME=/data BALELINK_HOST=0.0.0.0
VOLUME /data
EXPOSE 8787
CMD ["balelink", "serve"]
```

```bash
docker run -d -p 127.0.0.1:8787:8787 -e BALELINK_API_KEY=change-me -v balelink:/data balelink
```
