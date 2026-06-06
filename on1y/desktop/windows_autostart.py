"""Windows login autostart via Task Scheduler."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from on1y.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

TASK_NAME = "On1y"


def is_windows() -> bool:
    return sys.platform == "win32"


def autostart_installed() -> bool:
    if not is_windows():
        return False
    script = (
        f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
        "if ($t) { 'true' } else { 'false' }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        return result.stdout.strip().lower() == "true"
    except Exception:
        logger.exception("Failed to query autostart task")
        return False


def set_autostart(enabled: bool, *, root: Path | None = None) -> bool:
    if not is_windows():
        raise RuntimeError("autostart is only supported on Windows")
    root = root or PROJECT_ROOT
    script_name = "install-on1y-autostart.ps1" if enabled else "uninstall-on1y-autostart.ps1"
    script = root / "scripts" / script_name
    if not script.is_file():
        raise FileNotFoundError(f"missing script: {script}")
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        check=True,
        timeout=90,
        cwd=str(root),
    )
    return autostart_installed()
