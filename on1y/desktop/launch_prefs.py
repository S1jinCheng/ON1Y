"""Launch preferences consumed by scripts/start-on1y.ps1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from on1y.config import Settings, get_settings

_LAUNCH_FILE = "app-launch.json"


def launch_prefs_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.data_dir / _LAUNCH_FILE


def read_launch_prefs(settings: Settings | None = None) -> dict[str, Any]:
    path = launch_prefs_path(settings)
    if not path.is_file():
        return {"open_browser_on_start": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "open_browser_on_start": bool(data.get("open_browser_on_start", True)),
            }
    except json.JSONDecodeError:
        pass
    return {"open_browser_on_start": True}


def write_launch_prefs(
    *,
    open_browser_on_start: bool,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    payload = {"open_browser_on_start": bool(open_browser_on_start)}
    launch_prefs_path(settings).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
