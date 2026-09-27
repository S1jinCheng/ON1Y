"""Login startup for the desktop shell on Windows and macOS."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

from on1y.desktop import windows_autostart

_LABEL = "app.on1y.desktop"


def _desktop_executable() -> Path | None:
    raw = os.environ.get("ON1Y_DESKTOP_EXECUTABLE", "")
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() and path.is_file() else None


def autostart_supported() -> bool:
    return sys.platform == "win32" or (
        sys.platform == "darwin" and _desktop_executable() is not None
    )


def _agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"


def autostart_installed() -> bool:
    if sys.platform == "win32":
        return windows_autostart.autostart_installed()
    if sys.platform != "darwin":
        return False
    try:
        with _agent_path().open("rb") as stream:
            payload = plistlib.load(stream)
        executable = _desktop_executable()
        return bool(
            executable
            and payload.get("Label") == _LABEL
            and payload.get("RunAtLoad") is True
            and payload.get("ProgramArguments") == [str(executable), "--autostart"]
        )
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def set_autostart(enabled: bool, *, root: Path | None = None) -> bool:
    if sys.platform == "win32":
        return windows_autostart.set_autostart(enabled, root=root)
    if sys.platform != "darwin":
        raise RuntimeError("Login startup is supported on Windows and macOS")
    path = _agent_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return False
    executable = _desktop_executable()
    if executable is None:
        raise RuntimeError("请从 On1y 桌面应用中设置登录启动")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": _LABEL,
        "ProgramArguments": [str(executable), "--autostart"],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
    }
    temporary = path.with_suffix(".plist.tmp")
    temporary.write_bytes(plistlib.dumps(payload))
    temporary.chmod(0o600)
    temporary.replace(path)
    # LaunchAgents are read at the next login. Do not launch a second instance now.
    return autostart_installed()
