"""Shared by the gateway tests."""

from balelink import BaleClient
from balelink.gateway import Settings, create_app
from balelink.gateway.webhook import WebhookSender
from balelink.testing import FakeTransport

KEY = {"X-Api-Key": "k"}


class Env:
    """A gateway wired to FakeTransports and a recording webhook poster."""

    def __init__(self, tmp_path, **settings):
        self.tmp = tmp_path
        self.fakes = {}
        self.posts = []
        self.status = 200
        self.settings = Settings(
            directory=str(tmp_path), api_key="k", webhook_attempts=3, **settings
        )

        async def poster(url, body, headers):
            self.posts.append((url, body, headers))
            return self.status

        self.sender = WebhookSender(attempts=3, poster=poster, base_delay=0.01)

    def factory(self, name):
        fake = self.fakes.setdefault(name, FakeTransport(users_by_phone={"989121234567": 777}))
        return BaleClient(name, directory=self.tmp, transport=fake, min_send_interval=0)

    def app(self):
        return create_app(self.settings, client_factory=self.factory, sender=self.sender)


def login(c, name="a"):
    assert c.post("/sessions", json={"name": name}, headers=KEY).status_code == 201
    r = c.post(f"/sessions/{name}/login/code", json={"phone": "09121234567"}, headers=KEY)
    assert r.status_code == 200, r.text
    r = c.post(f"/sessions/{name}/login/verify", json={"code": "12345"}, headers=KEY)
    assert r.status_code == 200, r.text
    return r.json()
