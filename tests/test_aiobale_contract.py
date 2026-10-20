"""The adapter is the only code that touches aiobale. These checks fail loudly if a
new aiobale release renames something the adapter calls - before a user finds out."""

import inspect

import pytest

aiobale = pytest.importorskip("aiobale")

EXPECTED = {
    "start_phone_auth": ["phone_number"],
    "validate_code": ["code", "transaction_hash"],
    "validate_password": ["password"],
    "sign_out": [],
    "send_message": ["text", "chat_id", "chat_type", "reply_to"],
    "edit_message": [],
    "delete_messages": [],
    "set_reaction": [],
    "seen_chat": [],
    "start_typing": [],
    "stop_typing": [],
    "set_online": ["is_online"],
    "load_history": [],
    "download_file": [],
    "search_contact": [],
    "load_user": [],
    "load_dialogs": [],
    "start": ["signal_handling"],
    "stop": [],
    "send_document": [],
    "send_photo": [],
    "send_video": [],
    "send_voice": [],
    "send_audio": [],
    "send_gif": [],
}


@pytest.mark.parametrize("method, params", sorted(EXPECTED.items()))
def test_client_method_exists(method, params):
    fn = getattr(aiobale.Client, method, None)
    assert fn is not None, f"aiobale.Client.{method} is gone"
    have = set(inspect.signature(fn).parameters)
    missing = [p for p in params if p not in have]
    assert not missing, f"aiobale.Client.{method} lost parameters {missing}"


def test_dispatcher_and_errors_exist():
    dispatcher = aiobale.Dispatcher()  # `message` is created per instance
    assert callable(dispatcher.message)

    @dispatcher.message()
    async def handler(message):  # registering must not raise
        return None

    assert hasattr(aiobale.enums, "AuthErrors")


def test_adapter_imports():
    import balesdk._aiobale  # noqa: F401
