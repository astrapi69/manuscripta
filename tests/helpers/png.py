"""Tiny PNG generator used by fixtures; avoids a Pillow dependency."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def png_bytes(
    width: int = 8,
    height: int = 8,
    rgb: tuple[int, int, int] = (255, 0, 0),
) -> bytes:
    """Return the bytes of a tiny solid-colour PNG."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def write_png(path: Path, **kwargs) -> None:
    """Write a tiny PNG at ``path`` (creates parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(**kwargs))
