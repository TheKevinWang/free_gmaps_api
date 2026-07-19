from __future__ import annotations

import struct


def image_dimensions(data: bytes) -> tuple[int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24:
            raise ValueError("PNG image response is truncated.")
        width, height = struct.unpack(">II", data[16:24])
        if width <= 0 or height <= 0:
            raise ValueError("PNG image response has invalid dimensions.")
        return width, height
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Renderer response is not a JPEG or PNG image.")
    offset = 2
    while offset + 9 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 7 or offset + length > len(data):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            if width > 0 and height > 0:
                return width, height
            break
        offset += length
    raise ValueError("JPEG image response has no readable dimensions.")
