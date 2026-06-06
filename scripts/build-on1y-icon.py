"""Build assets/on1y.ico for the Windows desktop shortcut."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "on1y.ico"
SIZE = 256


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _render_rgba(size: int) -> bytes:
    """Black rounded square + white ring (letter O)."""
    pixels = bytearray(size * size * 4)
    cx = cy = (size - 1) / 2
    outer_r = size * 0.36
    inner_r = size * 0.24
    corner_r = size * 0.18
    half = size / 2 - corner_r

    def inside_rounded_square(x: float, y: float) -> bool:
        ax, ay = abs(x - cx), abs(y - cy)
        if ax <= half and ay <= half:
            return True
        if ax > half and ay > half:
            dx, dy = ax - half, ay - half
            return dx * dx + dy * dy <= corner_r * corner_r
        return ax <= half + corner_r and ay <= half + corner_r

    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            if not inside_rounded_square(x + 0.5, y + 0.5):
                pixels[i : i + 4] = b"\x00\x00\x00\x00"
                continue
            dx = x + 0.5 - cx
            dy = y + 0.5 - cy
            dist = math.hypot(dx, dy)
            if inner_r <= dist <= outer_r:
                pixels[i : i + 4] = b"\xff\xff\xff\xff"
            else:
                pixels[i : i + 4] = b"\x12\x12\x12\xff"

    return bytes(pixels)


def _png_bytes(size: int) -> bytes:
    raw = bytearray()
    rgba = _render_rgba(size)
    row_bytes = size * 4
    for y in range(size):
        raw.append(0)
        start = y * row_bytes
        raw.extend(rgba[start : start + row_bytes])

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _write_ico(path: Path, sizes: tuple[int, ...]) -> None:
    images = [(s, _png_bytes(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    blobs = bytearray()
    for size, png in images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries.extend(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset))
        blobs.extend(png)
        offset += len(png)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(entries) + bytes(blobs))


def main() -> None:
    _write_ico(OUT, (16, 32, 48, 64, 128, 256))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
