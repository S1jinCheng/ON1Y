"""Timezone for stats (Asia/Shanghai) with Windows / PyInstaller fallback."""

from __future__ import annotations

from datetime import timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo


@lru_cache(maxsize=1)
def stats_timezone() -> timezone:
    try:
        return ZoneInfo("Asia/Shanghai")
    except Exception:
        return timezone(timedelta(hours=8))
