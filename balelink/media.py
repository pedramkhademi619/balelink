"""Reading a picture's size or a voice note's length from the bytes themselves.

Bale shows a photo at the size you declare and a voice note with a waveform
sized by its duration, so they are worth getting right. No dependencies: these
read just enough of the common formats (PNG, JPEG, GIF, WebP; Ogg Opus).
"""

from __future__ import annotations

import struct
from typing import Optional, Tuple


def image_size(data: bytes) -> Optional[Tuple[int, int]]:
    """``(width, height)`` of a PNG, JPEG, GIF or WebP, or None if unknown."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"\xff\xd8":
            return _jpeg_size(data)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _webp_size(data)
    except (struct.error, IndexError):
        return None
    return None


def _jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        # SOF0..SOF15 except DHT(C4), JPG(C8), DAC(CC) carry the frame size.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None


def _webp_size(data: bytes) -> Optional[Tuple[int, int]]:
    kind = data[12:16]
    if kind == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L":
        bits = struct.unpack("<I", data[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    return None


def opus_duration_ms(data: bytes) -> Optional[int]:
    """Length of an Ogg Opus file (what Bale uses for voice notes), in ms."""
    if data[:4] != b"OggS":
        return None
    pre_skip = 0
    head = data.find(b"OpusHead")
    if head != -1 and len(data) >= head + 12:
        (pre_skip,) = struct.unpack("<H", data[head + 10 : head + 12])
    last = data.rfind(b"OggS")
    if last == -1 or len(data) < last + 14:
        return None
    (granule,) = struct.unpack("<q", data[last + 6 : last + 14])
    if granule <= 0:
        return None
    return int(max(granule - pre_skip, 0) * 1000 / 48000)
