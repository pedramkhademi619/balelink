# HTTP gateway

Run Bale accounts as a service so any language can use them - sessions, a
webhook for incoming messages, an API key, like WAHA does for WhatsApp.

```bash
pip install "balesdk[gateway]"
BALESDK_API_KEY=change-me balesdk serve        # http://127.0.0.1:8787
```

Interactive API docs: `http://127.0.0.1:8787/docs`. Every call except
`/health` needs the header `X-Api-Key: change-me`.

## Settings (environment)

| Variable | Default | |
|---|---|---|
| `BALESDK_API_KEY` | none | required header value. Without it only `127.0.0.1` is allowed. |
| `BALESDK_HOST` / `BALESDK_PORT` | `127.0.0.1` / `8787` | where to listen |
| `BALESDK_HOME` | `~/.balesdk` | logins and `gateway.json` |
| `BALESDK_AUTOSTART` | `true` | reconnect every saved login at startup |
| `BALESDK_WEBHOOK_ATTEMPTS` | `4` | tries per event (waits 1 s, 3 s, 9 s) |
| `BALESDK_WEBHOOK_TIMEOUT` | `10` | seconds per try |

## Walkthrough

```bash
H='X-Api-Key: change-me'; B=http://127.0.0.1:8787

curl -H "$H" -H 'content-type: application/json' $B/sessions \
  -d '{"name":"me","webhook_url":"https://example.com/hook","webhook_secret":"s3cret"}'

curl -H "$H" -H 'content-type: application/json' $B/sessions/me/login/code  -d '{"phone":"09121234567"}'
curl -H "$H" -H 'content-type: application/json' $B/sessions/me/login/verify -d '{"code":"12345"}'
# a two-step account answers 401 PASSWORD_REQUIRED: repeat with "password":"..."

curl -H "$H" -H 'content-type: application/json' $B/sessions/me/messages \
  -d '{"to":"09121234567","text":"hello"}'
```

## Endpoints

| | |
|---|---|
| `GET /health` | no key needed |
| `GET /sessions`, `POST /sessions`, `GET`/`DELETE /sessions/{name}` | manage accounts (`DELETE` logs out and deletes the login) |
| `POST /sessions/{name}/start`, `/stop` | connect / disconnect |
| `PUT /sessions/{name}/webhook` `{url, secret}` | `url: null` removes it |
| `POST /sessions/{name}/login/code` `{phone}` | ask Bale for a code |
| `POST /sessions/{name}/login/verify` `{code, password?}` | finish login (also connects) |
| `POST /sessions/{name}/messages` `{to, text, reply_to?, chat_id?}` | send text |
| `POST /sessions/{name}/files` `{to, data, kind?, caption?, file_name?, reply_to?, chat_id?}` | `data` is base64, up to 50 MB |
| `PATCH /sessions/{name}/messages/{id}` `{text}` | edit |
| `DELETE /sessions/{name}/messages/{id}?just_me=` | delete |
| `POST /sessions/{name}/messages/{id}/reaction` `{emoji}` | react |
| `POST /sessions/{name}/chats/{chat}/seen` | mark read |
| `GET /sessions/{name}/chats/{chat}/messages?limit=` | history, newest first |
| `GET /sessions/{name}/chats` | recent chats |

`to` is a phone number; set `"chat_id": true` to pass a chat id instead.
Editing, deleting, reacting and `reply_to` work on the last 500 messages the
session sent or saw (`404 MESSAGE_NOT_FOUND` otherwise).

Session `status` is one of `logged_out`, `code_sent`, `working`, `stopped`,
`failed` (with `error` set to a code).

## Errors

Always `{"error": {"code": "WRONG_CODE", "message": "..."}}`. Branch on `code`.
Status mapping: bad input 400/422, wrong password 401, banned 403, not found 404,
state conflict 409, rate limit 429, Bale unreachable 502.

## Webhook

Incoming messages (not your own) are POSTed as:

```json
{
  "event": "message",
  "session": "me",
  "message": {
    "id": 1234567890123,
    "chat": {"id": 123456789, "kind": "private"},
    "sender_id": 123456789,
    "from_me": false,
    "date": "2026-10-20T13:56:00+00:00",
    "timestamp": 1790000160.0,
    "text": "hi",
    "attachment": null
  }
}
```

With a `webhook_secret`, the header `X-Balesdk-Signature: sha256=<hex>` is the
HMAC-SHA256 of the raw body. Verify it before trusting the request:

```python
import hmac, hashlib


def valid(secret: str, body: bytes, header: str) -> bool:
    mine = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mine, header)
```

Any 2xx is success; anything else is retried, then dropped (and logged). The
webhook never delays receiving more messages.

## Running it for real

- Put it behind HTTPS (nginx/Caddy). The API key and your messages are
  otherwise in the clear.
- Keep `BALESDK_HOME` on a private disk and back it up: it holds the logins.
- Docker:

```dockerfile
FROM python:3.12-slim
RUN pip install "balesdk[gateway]"
ENV BALESDK_HOME=/data BALESDK_HOST=0.0.0.0
VOLUME /data
EXPOSE 8787
CMD ["balesdk", "serve"]
```

```bash
docker run -d -p 127.0.0.1:8787:8787 -e BALESDK_API_KEY=change-me -v balesdk:/data balesdk
```
