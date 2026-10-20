import pytest

from balesdk import BaleClient
from balesdk.testing import FakeTransport


@pytest.fixture
def fake():
    return FakeTransport(logged_in=True, users_by_phone={"989121234567": 777})


@pytest.fixture
async def bale(fake, tmp_path):
    client = BaleClient("test", directory=tmp_path, transport=fake, min_send_interval=0)
    async with client:
        yield client
