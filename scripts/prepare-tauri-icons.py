"""Generate desktop/src-tauri/icons/* and frontend logo from assets/only.ico (or PNG fallback)."""

from __future__ import annotations

import shutil
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "desktop" / "src-tauri" / "icons"
DESKTOP_UI_LOGO = ROOT / "desktop" / "ui" / "on1y-logo.png"
FRONTEND_LOGO = ROOT / "frontend" / "public" / "on1y-logo.png"

LOGO_CANDIDATES = (
    ROOT / "assets" / "only.ico",
    ROOT / "assets" / "on1y-logo.png",
    ROOT / "assets" / "On1y_Logo.png",
    ROOT / "assets" / "on1y.ico",
)


def _resolve_logo_source() -> Path:
    for path in LOGO_CANDIDATES:
        if path.is_file():
            return path
    names = ", ".join(p.name for p in LOGO_CANDIDATES)
    raise SystemExit(f"No logo found in assets/. Expected one of: {names}")


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _rgba_to_png_bytes(img) -> bytes:
    from PIL import Image

    if not isinstance(img, Image.Image):
        raise TypeError("expected PIL Image")
    size = img.size[0]
    raw = bytearray()
    rgba = img.convert("RGBA").tobytes()
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


def _resize_square(img, size: int):
    from PIL import Image

    src = img.convert("RGBA")
    w, h = src.size
    scale = min(size / w, size / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2), resized)
    return canvas


def _write_ico(path: Path, png_by_size: dict[int, bytes]) -> None:
    images = sorted(png_by_size.items(), key=lambda x: x[0])
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    blobs = bytearray()
    for size, png in images:
        w = 0 if size >= 256 else size
        h = w
        entries.extend(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset))
        blobs.extend(png)
        offset += len(png)
    path.write_bytes(header + bytes(entries) + bytes(blobs))


def _load_logo_image(source: Path):
    from PIL import Image

    img = Image.open(source)
    if getattr(img, "n_frames", 1) > 1:
        best = img
        best_area = 0
        for idx in range(img.n_frames):
            img.seek(idx)
            frame = img.copy()
            area = frame.size[0] * frame.size[1]
            if area > best_area:
                best_area = area
                best = frame
        return best
    return img


def main() -> None:
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow required: pip install pillow")

    source = _resolve_logo_source()
    OUT.mkdir(parents=True, exist_ok=True)
    FRONTEND_LOGO.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_UI_LOGO.parent.mkdir(parents=True, exist_ok=True)

    src = _load_logo_image(source)
    master = _resize_square(src, 512)

    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
    }
    png_by_size: dict[int, bytes] = {}
    for name, size in sizes.items():
        canvas = _resize_square(src, size) if size != 512 else master
        png = _rgba_to_png_bytes(canvas)
        (OUT / name).write_bytes(png)
        png_by_size[size] = png

    ico_path = OUT / "icon.ico"
    if source.suffix.lower() == ".ico":
        shutil.copy2(source, ico_path)
    else:
        ico_sizes: dict[int, bytes] = {}
        for size in (16, 32, 48, 64, 128, 256):
            ico_sizes[size] = _rgba_to_png_bytes(_resize_square(src, size))
        _write_ico(ico_path, ico_sizes)

    master.save(FRONTEND_LOGO, format="PNG")
    shutil.copy2(FRONTEND_LOGO, DESKTOP_UI_LOGO)

    for extra in (
        ROOT / "frontend" / "out" / "on1y-logo.png",
        ROOT / "dist" / "portable" / "app" / "frontend" / "out" / "on1y-logo.png",
    ):
        if extra.parent.is_dir():
            extra.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FRONTEND_LOGO, extra)

    print(f"Logo source: {source}")
    print(f"Wrote Tauri icons to {OUT}")
    print(f"Copied logo to {FRONTEND_LOGO}")
    print(f"Copied logo to {DESKTOP_UI_LOGO}")


if __name__ == "__main__":
    main()
