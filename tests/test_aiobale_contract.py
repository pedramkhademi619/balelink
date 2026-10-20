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
    "forward_messages": ["messages", "chat_id", "chat_type"],
    "pin_message": ["message_id", "message_date", "chat_id", "chat_type", "just_me"],
    "unpin_message": ["message_id", "message_date", "chat_id", "chat_type"],
    "remove_reaction": ["emojy", "message", "chat_id", "chat_type"],
    "delete_chat": ["chat_id", "chat_type"],
    "clear_chat": ["chat_id", "chat_type"],
    "load_contacts": [],
    "load_users": ["peers"],
    "add_contact": ["user_id"],
    "remove_contact": ["user_id"],
    "edit_user_local_name": ["name", "user_id"],
    "block_user": ["user_id"],
    "unblock_user": ["user_id"],
    "load_blocked_users": [],
    "load_full_user": ["chat_id", "chat_type"],
    "create_group": ["title", "users"],
    "get_full_group": ["chat_id"],
    "edit_group_title": ["title", "chat_id"],
    "edit_group_about": ["about", "chat_id"],
    "invite_users": ["chat_id", "users"],
    "kick_user": ["chat_id", "user_id"],
    "make_user_admin": ["chat_id", "user_id"],
    "remove_admin": ["chat_id", "user_id"],
    "leave_group": ["chat_id"],
    "get_group_link": ["chat_id"],
    "revoke_group_link": ["chat_id"],
    "join_chat": ["token_or_url"],
    "load_members": ["chat_id", "limit"],
    "edit_name": ["name"],
    "edit_about": ["about"],
    "edit_username": ["username"],
    "_build_chat": ["chat_id", "chat_type"],
    "_resolve_peer": ["chat"],
    "_ensure_info_message": [],
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
    assert callable(dispatcher.message_edited) and callable(dispatcher.message_deleted)

    @dispatcher.message()
    async def handler(message):  # registering must not raise
        return None

    assert hasattr(aiobale.enums, "AuthErrors")


def test_adapter_imports():
    import balelink._aiobale  # noqa: F401


def test_location_message_content_shape():
    """Locations are not a typed field in aiobale; we rely on this extra-field shape."""
    from aiobale.types import MessageContent

    from balelink._aiobale import _location_from, location_payload

    content = MessageContent(**{"7": {"1": location_payload(1.5, 2.5)}})
    assert _location_from(content).latitude == 1.5
    assert content.model_dump(by_alias=True, exclude_none=True)["7"]["1"]


def test_send_message_building_blocks_exist():
    from aiobale.methods import SendMessage  # noqa: F401
    from aiobale.utils import generate_id  # noqa: F401
