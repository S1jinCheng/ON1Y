"""Stage only distributable assets. Never copy local data, secrets or cookies."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def stage(root: Path) -> None:
    portable = root / "dist" / "portable"
    binary_name = "on1y.exe" if sys.platform == "win32" else "on1y"
    source = portable / "backend-build" / "on1y"
    if not (source / binary_name).is_file():
        raise FileNotFoundError(f"Build the backend first: {source / binary_name}")
    if not (root / "frontend" / "out" / "index.html").is_file():
        raise FileNotFoundError("Build frontend/out before staging")
    app = portable / "app"
    backend = portable / "backend"
    # These exact directories contain generated staging output only.
    for destination in (app, backend):
        if destination.is_symlink():
            raise ValueError(f"Refusing to replace symlink: {destination}")
        if destination.exists():
            shutil.rmtree(destination)
    (app / "config").mkdir(parents=True)
    shutil.copytree(source, backend / "on1y", symlinks=True)
    shutil.copytree(root / "frontend" / "out", app / "frontend" / "out")
    shutil.copytree(root / "sql", app / "sql")
    shutil.copy2(root / ".env.example", app / ".env.example")
    if sys.platform == "darwin":
        browsers = root / "build" / "playwright-browsers"
        if not browsers.is_dir():
            raise FileNotFoundError("Install Chromium with scripts/build-macos.sh first")
        shutil.copytree(
            browsers, app / "browsers", symlinks=True, ignore=shutil.ignore_patterns(".links")
        )
    for example in (root / "config").glob("*.example"):
        shutil.copy2(example, app / "config" / example.name)
    model = root / "data" / "models" / "PP-DocLayout-M"
    if (model / "inference.json").is_file() and (model / "inference.pdiparams").is_file():
        shutil.copytree(model, app / "models" / model.name)


if __name__ == "__main__":
    stage(Path(__file__).resolve().parent.parent)
