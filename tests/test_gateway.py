import asyncio
import base64
import json

from fastapi.testclient import TestClient
from gateway_helpers import KEY, login

from balelink.gateway.webhook import SIGNATURE_HEADER, WebhookSender, sign
from balelink.testing import FakeTransport


def test_auth_required(env):
    with TestClient(env.app()) as c:
        assert c.get("/health").json()["status"] == "ok"  # health is open
        assert c.get("/sessions").status_code == 401
        assert c.get("/sessions", headers={"X-Api-Key": "no"}).status_code == 401
        assert c.get("/sessions", headers=KEY).json() == []


def test_login_and_send(env):
    with TestClient(env.app()) as c:
        s = login(c)
        assert s["status"] == "working" and s["me"]["id"] == 1000
        r = c.post("/sessions/a/messages", json={"to": "09121234567", "text": "hi"}, headers=KEY)
        assert r.status_code == 200 and r.json()["chat"]["id"] == 777
        assert env.fakes["a"].sent[0].text == "hi"


def test_errors_are_json_with_stable_codes(env):
    with TestClient(env.app()) as c:
        c.post("/sessions", json={"name": "a"}, headers=KEY)
        r = c.post("/sessions/a/login/verify", json={"code": "1"}, headers=KEY)
        assert r.status_code == 409 and r.json()["error"]["code"] == "CODE_NOT_REQUESTED"
        c.post("/sessions/a/login/code", json={"phone": "09121234567"}, headers=KEY)
        r = c.post("/sessions/a/login/verify", json={"code": "0"}, headers=KEY)
        assert r.status_code == 400 and r.json()["error"]["code"] == "WRONG_CODE"
        r = c.post("/sessions/a/login/code", json={"phone": "12"}, headers=KEY)
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PHONE"
        r = c.post(
            "/sessions/a/messages", json={"to": "1", "text": "x", "chat_id": True}, headers=KEY
        )
        assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_CONNECTED"
        assert c.get("/sessions/zzz", headers=KEY).json()["error"]["code"] == "SESSION_NOT_FOUND"
        assert c.post("/sessions", json={"name": "a"}, headers=KEY).status_code == 409
        assert c.post("/sessions", json={"name": "../x"}, headers=KEY).status_code == 422


def test_unknown_recipient(env):
    with TestClient(env.app()) as c:
        login(c)
        r = c.post("/sessions/a/messages", json={"to": "09350000000", "text": "x"}, headers=KEY)
        assert r.status_code == 404 and r.json()["error"]["code"] == "CHAT_NOT_FOUND"


def test_two_step_password(env):
    env.fakes["a"] = FakeTransport(password="pw")
    with TestClient(env.app()) as c:
        c.post("/sessions", json={"name": "a"}, headers=KEY)
        c.post("/sessions/a/login/code", json={"phone": "09121234567"}, headers=KEY)
        r = c.post("/sessions/a/login/verify", json={"code": "12345"}, headers=KEY)
        assert r.status_code == 401 and r.json()["error"]["code"] == "PASSWORD_REQUIRED"
        r = c.post(
            "/sessions/a/login/verify", json={"code": "12345", "password": "pw"}, headers=KEY
        )
        assert r.status_code == 200


def test_edit_react_delete_reply_and_files(env):
    with TestClient(env.app()) as c:
        login(c)
        sent = c.post(
            "/sessions/a/messages", json={"to": "5", "chat_id": True, "text": "a"}, headers=KEY
        ).json()
        mid = sent["id"]
        assert (
            c.patch(f"/sessions/a/messages/{mid}", json={"text": "b"}, headers=KEY).json()["text"]
            == "b"
        )
        assert (
            c.post(
                f"/sessions/a/messages/{mid}/reaction", json={"emoji": "👍"}, headers=KEY
            ).status_code
            == 200
        )
        r = c.post(
            "/sessions/a/messages",
            json={"to": "5", "chat_id": True, "text": "c", "reply_to": mid},
            headers=KEY,
        )
        assert env.fakes["a"].sent[-1].raw["reply_to"] == mid and r.status_code == 200
        data = base64.b64encode(b"hello").decode()
        r = c.post(
            "/sessions/a/files",
            json={"to": "5", "chat_id": True, "data": data, "kind": "photo", "caption": "cap"},
            headers=KEY,
        )
        assert r.status_code == 200 and env.fakes["a"].sent_files[0].kind.value == "photo"
        r = c.post(
            "/sessions/a/files", json={"to": "5", "chat_id": True, "data": "!!"}, headers=KEY
        )
        assert r.json()["error"]["code"] == "INVALID_FILE_DATA"
        assert c.delete(f"/sessions/a/messages/{mid}", headers=KEY).status_code == 200
        assert (
            c.delete(f"/sessions/a/messages/{mid}", headers=KEY).json()["error"]["code"]
            == "MESSAGE_NOT_FOUND"
        )
        assert c.post("/sessions/a/chats/5/seen", headers=KEY).status_code == 200


def test_webhook_signed_delivery(env):
    with TestClient(env.app()) as c:
        login(c)
        r = c.put("/sessions/a/webhook", json={"url": "http://hook/x", "secret": "s3"}, headers=KEY)
        assert r.json()["webhook"] == {
            "url": "http://hook/x",
            "events": ["message"],
            "signed": True,
            "headers": [],
            "retries": None,
        }
        c.portal.call(lambda: env.fakes["a"].deliver("hello", chat_id=42))

        async def settle():
            for _ in range(100):
                if env.posts:
                    return
                await asyncio.sleep(0.01)

        c.portal.call(settle)
        url, body, headers = env.posts[0]
        assert url == "http://hook/x"
        payload = json.loads(body)
        assert payload["event"] == "message" and payload["session"] == "a"
        assert payload["me"]["id"] == 1000 and payload["id"] and payload["timestamp"]
        assert payload["payload"]["text"] == "hello" and payload["payload"]["chat"]["id"] == 42
        assert headers[SIGNATURE_HEADER] == sign("s3", body)


def test_sign_is_stable():
    assert sign("k", b"x").startswith("sha256=") and sign("k", b"x") == sign("k", b"x")
    assert sign("k", b"x") != sign("j", b"x")


async def test_webhook_retries_then_succeeds():
    calls = []

    async def poster(url, body, headers):
        calls.append(1)
        return 500 if len(calls) < 3 else 204

    s = WebhookSender(attempts=4, poster=poster, base_delay=0.001)
    assert await s._deliver("http://x", None, {"a": 1}) is True
    assert len(calls) == 3


async def test_webhook_gives_up_and_survives_errors():
    async def poster(url, body, headers):
        raise OSError("down")

    s = WebhookSender(attempts=2, poster=poster, base_delay=0.001)
    assert await s._deliver("http://x", None, {}) is False


def test_state_survives_restart(env):
    with TestClient(env.app()) as c:
        login(c)
        c.put("/sessions/a/webhook", json={"url": "http://hook/x", "secret": "s"}, headers=KEY)
    state = env.tmp / "gateway.json"
    assert oct(state.stat().st_mode & 0o777) == "0o600"

    # a new gateway, same directory: the logged-in fake is "restored" and restarted
    env.fakes["a"].logged_in = True
    env.fakes["a"]._connected = False
    with TestClient(env.app()) as c:
        s = c.get("/sessions/a", headers=KEY).json()
        assert s["status"] == "working"
        assert s["webhook"]["url"] == "http://hook/x" and s["webhook"]["signed"] is True


def test_delete_session_logs_out(env):
    with TestClient(env.app()) as c:
        login(c)
        assert c.delete("/sessions/a", headers=KEY).json() == {"deleted": "a"}
        assert c.get("/sessions", headers=KEY).json() == []
        assert not env.fakes["a"].logged_in


def test_stop_and_start(env):
    with TestClient(env.app()) as c:
        login(c)
        assert c.post("/sessions/a/stop", headers=KEY).json()["status"] == "stopped"
        assert c.post("/sessions/a/start", headers=KEY).json()["status"] == "working"


def test_start_failure_is_reported(env):
    env.fakes["a"] = FakeTransport(logged_in=True, fail_connect=True)
    with TestClient(env.app()) as c:
        c.post("/sessions", json={"name": "a"}, headers=KEY)
        r = c.post("/sessions/a/start", headers=KEY)
        assert r.status_code == 502 and r.json()["error"]["code"] == "CONNECTION_FAILED"
        s = c.get("/sessions/a", headers=KEY).json()
        assert s["status"] == "failed" and s["error"] == "CONNECTION_FAILED"
