"""Generate desktop/src-tauri/icons/* from the On1y logo raster."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "desktop" / "src-tauri" / "icons"
ASSETS_ICO = ROOT / "assets" / "on1y.ico"

_icon_mod_path = ROOT / "scripts" / "build-on1y-icon.py"
_spec = importlib.util.spec_from_file_location("build_on1y_icon", _icon_mod_path)
_icon_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_icon_mod)
_png_bytes = _icon_mod._png_bytes
_write_ico = _icon_mod._write_ico


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
    }
    for name, size in sizes.items():
        (OUT / name).write_bytes(_png_bytes(size))
    _write_ico(OUT / "icon.ico", (16, 32, 48, 64, 128, 256))
    if ASSETS_ICO.is_file():
        shutil.copy2(ASSETS_ICO, OUT / "icon.ico")
    print(f"Wrote Tauri icons to {OUT}")


if __name__ == "__main__":
    main()
