import asyncio

import pytest

from balelink import ChatNotFound, Location
from balelink import filters as F

# ---- locations, media kinds --------------------------------------------------------------


async def test_send_and_receive_location(bale, fake):
    got = []
    bale.on_message(F.location)(lambda m: got.append(m.location))
    await fake.deliver(chat_id=5, location=Location(29.65, 52.5))
    await asyncio.sleep(0.02)
    assert got == [Location(29.65, 52.5)]

    sent = await bale.send_location(5, 35.7, 51.4)
    assert sent.location == Location(35.7, 51.4) and sent.kind == "location"
    with pytest.raises(ValueError):
        await bale.send_location(5, 123, 0)


async def test_reply_location_and_maps_url(bale, fake):
    incoming = await fake.deliver("where?", chat_id=7)
    sent = await incoming.reply_location(1.5, 2.5)
    assert fake.sent[-1].raw["reply_to"] == incoming.id and sent.location.maps_url.endswith(
        "1.5,2.5"
    )


async def test_media_filters_and_kind(bale, fake):
    from balelink import Attachment, FileKind

    seen = []
    bale.on_message(F.photo)(lambda m: seen.append(("photo", m.attachment.width, m.caption)))
    bale.on_message(F.voice)(lambda m: seen.append(("voice", m.attachment.duration_ms)))
    await fake.deliver(
        attachment=Attachment(1, 2, kind=FileKind.PHOTO, width=540, height=1170, caption="hi")
    )
    await fake.deliver(attachment=Attachment(3, 4, kind=FileKind.VOICE, duration_ms=3894))
    await fake.deliver("plain")
    await asyncio.sleep(0.03)
    assert seen == [("photo", 540, "hi"), ("voice", 3894)]


# ---- events ---------------------------------------------------------------------------------


async def test_edited_and_deleted_and_generic_events(bale, fake):
    edited, deleted, events = [], [], []
    bale.on_edited(F.private)(lambda m: edited.append(m.text))
    bale.on_deleted(lambda chat, ids: deleted.append((chat.id, ids)))
    bale.on_event(lambda name, payload: events.append(name))

    m = await fake.deliver("first", chat_id=3)
    await fake.deliver_edit(m, "second")
    await fake.deliver_revoke(3, [m.id])
    await asyncio.sleep(0.03)
    assert edited == ["second"]
    assert deleted == [(3, [m.id])]
    assert events == ["message.any", "message", "message.edited", "message.revoked"]


async def test_own_message_is_message_any_only(bale, fake):
    events = []
    bale.on_event(lambda name, payload: events.append(name))
    await fake.deliver("mine", sender_id=fake.me_id)
    await asyncio.sleep(0.02)
    assert events == ["message.any"]


# ---- forwarding, pinning, chats ----------------------------------------------------------------


async def test_forward_pin_unreact_and_chat_removal(bale, fake):
    m = await fake.deliver("x", chat_id=3)
    await m.forward("09121234567")
    await bale.forward_messages([m], 8)
    await m.pin()
    await m.unpin()
    await m.unreact("👍")
    await bale.clear_chat(3)
    await bale.delete_chat(3)
    assert fake.forwarded == [(777, [m.id]), (8, [m.id])]
    assert fake.pinned == [(m.id, True, False), (m.id, False, False)]
    assert fake.cleared == [3] and fake.chats_deleted == [3]


# ---- contacts ---------------------------------------------------------------------------------------


async def test_contacts_lifecycle(bale, fake):
    assert (await bale.check_phone("09121234567")).id == 777
    assert await bale.check_phone("09350000000") is None

    await bale.add_contact("09121234567")
    assert [u.id for u in await bale.contacts()] == [777]
    await bale.rename_contact(777, "Ali")
    assert (await bale.contacts())[0].name == "Ali"

    await bale.block(777)
    assert [u.id for u in await bale.blocked()] == [777]
    info = await bale.user_info(777)
    assert info.is_blocked and info.is_contact and info.about

    await bale.unblock(777)
    await bale.remove_contact(777)
    assert await bale.blocked() == [] and await bale.contacts() == []


# ---- groups ------------------------------------------------------------------------------------------


async def test_group_lifecycle(bale, fake):
    g = await bale.create_group("Team", ["09121234567", 55])
    assert g.title == "Team" and g.members_count == 3
    await bale.set_group_title(g, "Team 2")
    await bale.set_group_about(g.id, "about")
    info = await bale.group_info(g)
    assert (info.title, info.about) == ("Team 2", "about")

    await bale.add_members(g, [66])
    assert {m.user_id for m in await bale.members(g)} == {fake.me_id, 777, 55, 66}
    await bale.set_admin(g, 55)
    assert next(m for m in await bale.members(g) if m.user_id == 55).is_admin
    await bale.set_admin(g, 55, False)
    await bale.remove_member(g, 66)
    assert (await bale.group_info(g)).members_count == 3

    link = await bale.group_link(g)
    assert (await bale.join_group(link)).id == g.id
    assert await bale.group_link(g, revoke=True) != link

    await bale.leave_group(g)
    with pytest.raises(ChatNotFound):
        await bale.group_info(g)


async def test_profile(bale, fake):
    await bale.set_name("New")
    await bale.set_about("Hello")
    await bale.set_username("newuser")
    assert fake.profile == {"name": "New", "about": "Hello", "username": "newuser"}
