import base64
import struct

from balelink.media import image_size, opus_duration_ms

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAADCAYAAAC56t6BAAAAEklEQVR4nGP4z8Dwn4EBCAAAAP//AwAH/wL/dM7n3QAAAABJRU5ErkJggg=="
)


def test_png_size():
    assert image_size(PNG) == (2, 3)


def test_gif_size():
    assert image_size(b"GIF89a" + struct.pack("<HH", 7, 9) + b"\x00" * 8) == (7, 9)


def test_jpeg_size():
    jpeg = b"\xff\xd8" + b"\xff\xc0" + struct.pack(">HBHH", 11, 8, 40, 30) + b"\x00" * 8
    assert image_size(jpeg) == (30, 40)


def test_webp_vp8x_size():
    body = (
        b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00" * 4
        + (99).to_bytes(3, "little")
        + (49).to_bytes(3, "little")
    )
    assert image_size(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body) == (100, 50)


def test_unknown_or_truncated_is_none():
    assert image_size(b"not an image") is None
    assert image_size(b"\x89PNG\r\n\x1a\n") is None
    assert image_size(b"") is None


def test_opus_duration():
    head = b"OggS" + b"\x00" * 22 + b"OpusHead" + b"\x01\x01" + struct.pack("<H", 312)
    last = b"OggS\x00\x04" + struct.pack("<q", 312 + 48000 * 2) + b"\x00" * 8
    assert opus_duration_ms(head + last) == 2000
    assert opus_duration_ms(b"nope") is None


def test_chat_kind_mapping():
    from balelink import ChatKind
    from balelink._aiobale import kind_from_name

    assert kind_from_name(1) is ChatKind.PRIVATE
    assert kind_from_name(2) is ChatKind.GROUP
    assert kind_from_name(4) is ChatKind.BOT
    assert kind_from_name("super_group") is ChatKind.SUPER_GROUP
    assert kind_from_name(0) is ChatKind.UNKNOWN
