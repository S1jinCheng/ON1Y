# PyInstaller spec — bundled on1y backend for Windows desktop release.
# Run via: scripts/package-release.ps1

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve().parent

entry = str(root / "packaging" / "pyinstaller_entry.py")

datas: list[tuple[str, str]] = [
    (str(root / "sql"), "sql"),
]

hiddenimports: list[str] = list(collect_submodules("on1y"))

for pkg in (
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "anyio",
    "httpx",
    "httpcore",
    "h11",
    "feedparser",
    "yt_dlp",
    "multipart",
    "bcrypt",
    "jwt",
    "tzdata",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        hiddenimports += pkg_hidden
    except Exception:
        hiddenimports.append(pkg)

block_cipher = None

a = Analysis(
    [entry],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="on1y",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="on1y",
)
