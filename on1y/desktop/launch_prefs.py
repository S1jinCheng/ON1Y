"""Machine-level app preferences (data/app-launch.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from on1y.config import Settings, get_settings

_LAUNCH_FILE = "app-launch.json"

CloseWindowAction = Literal["hide", "quit"]


def launch_prefs_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.data_dir / _LAUNCH_FILE


def _default_payload() -> dict[str, Any]:
    return {
        "open_browser_on_start": True,
        "close_window_action": "quit",
        "data_dir_override": None,
    }


def read_launch_prefs(settings: Settings | None = None) -> dict[str, Any]:
    path = launch_prefs_path(settings)
    base = _default_payload()
    if not path.is_file():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return base
        action = str(data.get("close_window_action") or "quit").strip().lower()
        if action not in {"hide", "quit"}:
            action = "quit"
        override = data.get("data_dir_override")
        override_str = str(override).strip() if override else ""
        return {
            "open_browser_on_start": bool(data.get("open_browser_on_start", True)),
            "close_window_action": action,
            "data_dir_override": override_str or None,
        }
    except json.JSONDecodeError:
        return base


def _write_prefs_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_launch_prefs(
    *,
    open_browser_on_start: bool | None = None,
    close_window_action: CloseWindowAction | None = None,
    data_dir_override: str | None = ...,  # type: ignore[assignment]
    settings: Settings | None = None,
) -> dict[str, Any]:
    from on1y.config import PROJECT_ROOT

    settings = settings or get_settings()
    current = read_launch_prefs(settings)
    if open_browser_on_start is not None:
        current["open_browser_on_start"] = bool(open_browser_on_start)
    if close_window_action is not None:
        action = str(close_window_action).strip().lower()
        current["close_window_action"] = action if action in {"hide", "quit"} else "quit"
    if data_dir_override is not ...:
        raw = str(data_dir_override or "").strip()
        current["data_dir_override"] = raw or None
    _write_prefs_file(launch_prefs_path(settings), current)
    bootstrap = PROJECT_ROOT / "data" / _LAUNCH_FILE
    if bootstrap != launch_prefs_path(settings):
        _write_prefs_file(bootstrap, current)
    return current


def resolve_data_dir_for_boot(
    project_root: Path,
    *,
    settings: Settings | None = None,
) -> Path:
    """Pick data directory for desktop boot (override in launch prefs or default)."""
    settings = settings or get_settings()
    prefs = read_launch_prefs(settings)
    override = prefs.get("data_dir_override")
    if override:
        path = Path(str(override)).expanduser()
        if not path.is_absolute():
            path = (project_root / path).resolve()
        return path
    return settings.data_dir.resolve()
