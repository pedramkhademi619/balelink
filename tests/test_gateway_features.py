import asyncio
import base64
import json

from fastapi.testclient import TestClient
from gateway_helpers import KEY, login

from balelink import Attachment, FileKind, Location


def settle(c, env, count=1, timeout=1.0):
    async def wait():
        end = asyncio.get_running_loop().time() + timeout
        while len(env.posts) < count and asyncio.get_running_loop().time() < end:
            await asyncio.sleep(0.01)

    c.portal.call(wait)


def deliver(c, env, *args, **kw):
    return c.portal.call(lambda: env.fakes["a"].deliver(*args, **kw))


def events(env):
    return [json.loads(body)["event"] for _, body, _ in env.posts]


def test_multiple_webhooks_with_event_filters_and_headers(env):
    with TestClient(env.app()) as c:
        login(c)
        r = c.put(
            "/sessions/a/webhooks",
            json={
                "webhooks": [
                    {"url": "http://one/x", "events": ["message"], "headers": {"X-Token": "t"}},
                    {"url": "http://two/x", "events": ["message.edited", "message.revoked"]},
                    {"url": "http://all/x", "events": ["*"], "retries": 2},
                ]
            },
            headers=KEY,
        )
        assert [w["url"] for w in r.json()["webhooks"]] == [
            "http://one/x",
            "http://two/x",
            "http://all/x",
        ]
        assert r.json()["webhooks"][0]["headers"] == ["X-Token"]  # names only, never values

        m = deliver(c, env, "hi", chat_id=42)
        c.portal.call(lambda: env.fakes["a"].deliver_edit(m, "hi2"))
        c.portal.call(lambda: env.fakes["a"].deliver_revoke(42, [m.id]))
        settle(c, env, 7)
        by_url = {}
        for url, body, headers in env.posts:
            by_url.setdefault(url, []).append((json.loads(body)["event"], headers))
        assert [e for e, _ in by_url["http://one/x"]] == ["message"]
        assert by_url["http://one/x"][0][1]["X-Token"] == "t"
        assert [e for e, _ in by_url["http://two/x"]] == ["message.edited", "message.revoked"]
        assert {"message", "message.any", "message.edited", "message.revoked"} <= {
            e for e, _ in by_url["http://all/x"]
        }


def test_unknown_event_is_rejected(env):
    with TestClient(env.app()) as c:
        login(c)
        r = c.put(
            "/sessions/a/webhooks",
            json={"webhooks": [{"url": "http://x", "events": ["nope"]}]},
            headers=KEY,
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_EVENT"


def test_ignore_rules(env):
    with TestClient(env.app()) as c:
        login(c)
        c.put("/sessions/a/webhook", json={"url": "http://h/x", "events": ["message"]}, headers=KEY)
        r = c.put(
            "/sessions/a/config",
            json={"ignore_groups": True, "metadata": {"team": "x"}},
            headers=KEY,
        )
        assert r.json()["config"] == {
            "ignore": {"groups": True, "private": False},
            "metadata": {"team": "x"},
        }
        from balelink import ChatKind

        c.portal.call(lambda: env.fakes["a"].deliver("g", chat_id=5, kind=ChatKind.GROUP))
        deliver(c, env, "p", chat_id=6)
        settle(c, env, 1)
        assert [json.loads(b)["payload"]["text"] for _, b, _ in env.posts] == ["p"]


def test_session_status_events(env):
    with TestClient(env.app()) as c:
        c.post(
            "/sessions",
            json={"name": "a", "webhooks": [{"url": "http://h/x", "events": ["session.status"]}]},
            headers=KEY,
        )
        c.post("/sessions/a/login/code", json={"phone": "09121234567"}, headers=KEY)
        c.post("/sessions/a/login/verify", json={"code": "12345"}, headers=KEY)
        c.post("/sessions/a/stop", headers=KEY)
        c.post("/sessions/a/restart", headers=KEY)
        c.post("/sessions/a/logout", headers=KEY)
        settle(c, env, 6)
        statuses = [json.loads(b)["payload"]["status"] for _, b, _ in env.posts]
        assert (
            statuses == ["code_sent", "working", "stopped", "working", "logged_out"]
            or statuses[-1] == "logged_out"
        )
        assert "working" in statuses and "stopped" in statuses
        # logout keeps the session so it can log in again
        assert c.get("/sessions/a", headers=KEY).json()["status"] == "logged_out"


def test_location_roundtrip_and_media_json(env):
    with TestClient(env.app()) as c:
        login(c)
        r = c.post(
            "/sessions/a/location",
            json={"to": "5", "chat_id": True, "latitude": 29.6, "longitude": 52.5},
            headers=KEY,
        )
        assert (
            r.status_code == 200
            and r.json()["location"]["latitude"] == 29.6
            and r.json()["kind"] == "location"
        )
        assert (
            c.post(
                "/sessions/a/location",
                json={"to": "5", "chat_id": True, "latitude": 99, "longitude": 0},
                headers=KEY,
            ).status_code
            == 422
        )

        c.put("/sessions/a/webhook", json={"url": "http://h/x", "events": ["message"]}, headers=KEY)
        c.portal.call(lambda: env.fakes["a"].deliver(chat_id=9, location=Location(1.5, 2.5)))
        c.portal.call(
            lambda: env.fakes["a"].deliver(
                chat_id=9,
                attachment=Attachment(
                    1,
                    2,
                    name="p.jpg",
                    mime_type="image/jpeg",
                    kind=FileKind.PHOTO,
                    width=10,
                    height=20,
                    caption="cap",
                ),
            )
        )
        settle(c, env, 2)
        loc, photo = (json.loads(b)["payload"] for _, b, _ in env.posts)
        assert loc["location"]["maps_url"].endswith("1.5,2.5")
        assert photo["media"]["kind"] == "photo" and photo["media"]["width"] == 10
        assert photo["media"]["url"].endswith(f"/messages/{photo['id']}/media")


def test_media_download(env):
    with TestClient(env.app()) as c:
        login(c)
        m = c.portal.call(
            lambda: env.fakes["a"].deliver(
                chat_id=9, attachment=Attachment(1, 2, name="p.jpg", mime_type="image/jpeg")
            )
        )
        r = c.get(f"/sessions/a/messages/{m.id}/media", headers=KEY)
        assert (
            r.status_code == 200
            and r.content == b"fake-bytes"
            and r.headers["content-type"] == "image/jpeg"
        )
        t = c.post(
            "/sessions/a/messages", json={"to": "5", "chat_id": True, "text": "x"}, headers=KEY
        ).json()
        assert (
            c.get(f"/sessions/a/messages/{t['id']}/media", headers=KEY).json()["error"]["code"]
            == "NO_MEDIA"
        )


def test_send_file_sources(env):
    with TestClient(env.app()) as c:
        login(c)
        data = base64.b64encode(b"x").decode()
        both = c.post(
            "/sessions/a/files",
            json={"to": "5", "chat_id": True, "data": data, "url": "http://x/y"},
            headers=KEY,
        )
        assert both.json()["error"]["code"] == "INVALID_FILE_SOURCE"
        neither = c.post("/sessions/a/files", json={"to": "5", "chat_id": True}, headers=KEY)
        assert neither.json()["error"]["code"] == "INVALID_FILE_SOURCE"
        # private addresses are refused (no network access needed to prove it)
        priv = c.post(
            "/sessions/a/images",
            json={"to": "5", "chat_id": True, "url": "http://127.0.0.1:1/a.png"},
            headers=KEY,
        )
        assert priv.status_code == 422 and priv.json()["error"]["code"] == "URL_NOT_ALLOWED"
        bad = c.post(
            "/sessions/a/images",
            json={"to": "5", "chat_id": True, "url": "file:///etc/passwd"},
            headers=KEY,
        )
        assert bad.json()["error"]["code"] == "INVALID_URL"
        # the convenience endpoints force the kind
        c.post("/sessions/a/images", json={"to": "5", "chat_id": True, "data": data}, headers=KEY)
        c.post("/sessions/a/voice", json={"to": "5", "chat_id": True, "data": data}, headers=KEY)
        c.post("/sessions/a/videos", json={"to": "5", "chat_id": True, "data": data}, headers=KEY)
        c.post(
            "/sessions/a/files",
            json={"to": "5", "chat_id": True, "data": data, "file_name": "a.png"},
            headers=KEY,
        )
        assert [f.kind.value for f in env.fakes["a"].sent_files] == [
            "photo",
            "voice",
            "video",
            "photo",
        ]


def test_forward_pin_unreact_typing_chats(env):
    with TestClient(env.app()) as c:
        login(c)
        sent = c.post(
            "/sessions/a/messages", json={"to": "5", "chat_id": True, "text": "a"}, headers=KEY
        ).json()
        mid = sent["id"]
        assert (
            c.post(
                "/sessions/a/forward", json={"to": "09121234567", "message_ids": [mid]}, headers=KEY
            ).status_code
            == 200
        )
        assert c.post(f"/sessions/a/messages/{mid}/pin", headers=KEY).status_code == 200
        assert (
            c.post(
                f"/sessions/a/messages/{mid}/pin", json={"just_me": True}, headers=KEY
            ).status_code
            == 200
        )
        assert c.delete(f"/sessions/a/messages/{mid}/pin", headers=KEY).status_code == 200
        assert (
            c.delete(
                f"/sessions/a/messages/{mid}/reaction?emoji=%F0%9F%91%8D", headers=KEY
            ).status_code
            == 200
        )
        assert c.post(
            "/sessions/a/typing", json={"to": "5", "chat_id": True}, headers=KEY
        ).json() == {"typing": True}
        assert c.post("/sessions/a/chats/5/clear", headers=KEY).status_code == 200
        assert c.delete("/sessions/a/chats/5", headers=KEY).status_code == 200
        fake = env.fakes["a"]
        assert fake.forwarded == [(777, [mid])]
        assert fake.pinned == [(mid, True, False), (mid, True, True), (mid, False, False)]
        assert fake.cleared == [5] and fake.chats_deleted == [5]
        assert fake.typing_log == [(5, True)]


def test_contacts_endpoints(env):
    with TestClient(env.app()) as c:
        login(c)
        assert c.get("/sessions/a/contacts/check-exists?phone=09121234567", headers=KEY).json() == {
            "exists": True,
            "user_id": 777,
        }
        assert c.get("/sessions/a/contacts/check-exists?phone=09350000000", headers=KEY).json() == {
            "exists": False,
            "user_id": None,
        }
        assert (
            c.post("/sessions/a/contacts", json={"user": "09121234567"}, headers=KEY).status_code
            == 200
        )
        assert [u["id"] for u in c.get("/sessions/a/contacts", headers=KEY).json()] == [777]
        assert (
            c.put("/sessions/a/contacts/777", json={"name": "Ali"}, headers=KEY).json()["name"]
            == "Ali"
        )
        assert c.post("/sessions/a/contacts/777/block", headers=KEY).status_code == 200
        assert [u["id"] for u in c.get("/sessions/a/contacts/blocked", headers=KEY).json()] == [777]
        info = c.get("/sessions/a/contacts/777", headers=KEY).json()
        assert info["is_blocked"] is True and info["name"] == "Ali"
        assert c.post("/sessions/a/contacts/777/unblock", headers=KEY).status_code == 200
        assert c.delete("/sessions/a/contacts/777", headers=KEY).status_code == 200
        assert c.get("/sessions/a/contacts", headers=KEY).json() == []


def test_group_endpoints(env):
    with TestClient(env.app()) as c:
        login(c)
        g = c.post(
            "/sessions/a/groups",
            json={"title": "Team", "members": ["09121234567", "55"]},
            headers=KEY,
        )
        assert g.status_code == 201
        gid = g.json()["id"]
        assert (
            c.put(
                f"/sessions/a/groups/{gid}", json={"title": "T2", "about": "ab"}, headers=KEY
            ).json()["title"]
            == "T2"
        )
        assert (
            c.post(
                f"/sessions/a/groups/{gid}/members", json={"members": ["66"]}, headers=KEY
            ).status_code
            == 200
        )
        ids = {m["user_id"] for m in c.get(f"/sessions/a/groups/{gid}/members", headers=KEY).json()}
        assert {777, 55, 66} <= ids
        assert c.post(f"/sessions/a/groups/{gid}/admins/55", headers=KEY).status_code == 200
        assert next(
            m
            for m in c.get(f"/sessions/a/groups/{gid}/members", headers=KEY).json()
            if m["user_id"] == 55
        )["is_admin"]
        assert c.delete(f"/sessions/a/groups/{gid}/admins/55", headers=KEY).status_code == 200
        assert c.delete(f"/sessions/a/groups/{gid}/members/66", headers=KEY).status_code == 200
        link = c.get(f"/sessions/a/groups/{gid}/invite-link", headers=KEY).json()["link"]
        assert (
            c.post("/sessions/a/groups/join", json={"link": link}, headers=KEY).json()["id"] == gid
        )
        assert (
            c.post(f"/sessions/a/groups/{gid}/invite-link/revoke", headers=KEY).json()["link"]
            != link
        )
        assert c.post(f"/sessions/a/groups/{gid}/leave", headers=KEY).status_code == 200
        assert (
            c.get(f"/sessions/a/groups/{gid}", headers=KEY).json()["error"]["code"]
            == "CHAT_NOT_FOUND"
        )


def test_profile_ping_version_me(env):
    with TestClient(env.app()) as c:
        assert c.get("/ping").json() == {"ping": "pong"}
        assert "message.edited" in c.get("/version", headers=KEY).json()["events"]
        login(c)
        assert c.get("/sessions/a/me", headers=KEY).json()["id"] == 1000
        r = c.put(
            "/sessions/a/profile", json={"name": "N", "about": "A", "username": "u"}, headers=KEY
        )
        assert r.json()["updated"] == ["name", "about", "username"]
        assert env.fakes["a"].profile == {"name": "N", "about": "A", "username": "u"}


def test_history_before(env):
    with TestClient(env.app()) as c:
        login(c)
        assert (
            c.get("/sessions/a/chats/3/messages?before=1790000000&limit=5", headers=KEY).json()
            == []
        )
