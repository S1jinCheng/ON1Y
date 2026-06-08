"""Per-user auto-sync timestamps (gap detection for catch-up backfill)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_KEY = "last_auto_sync_at"


def _settings_path(user_id: int) -> Path:
    from on1y.user.paths import user_dir

    return user_dir(user_id) / "sync_settings.json"


def read_last_auto_sync_at(*, user_id: int) -> datetime | None:
    path = _settings_path(user_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get(_KEY) if isinstance(data, dict) else None
        if not raw:
            return None
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        logger.debug("Could not read %s for user %s", _KEY, user_id, exc_info=True)
        return None


def write_last_auto_sync_at(*, user_id: int, at: datetime | None = None) -> None:
    path = _settings_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    ts = at or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    data[_KEY] = ts.astimezone(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def should_backfill_after_gap(*, user_id: int, now: datetime | None = None) -> bool:
    """True when the last successful auto-sync was on an earlier UTC calendar day."""
    last = read_last_auto_sync_at(user_id=user_id)
    if last is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    last_utc = last.astimezone(timezone.utc)
    current_utc = current.astimezone(timezone.utc)
    return last_utc.date() < current_utc.date()
