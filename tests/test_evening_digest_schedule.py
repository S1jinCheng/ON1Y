"""Evening digest scheduler timing."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from on1y.digest.evening_auto import _seconds_until, _today_run_at


def test_seconds_until_digest_hour() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 6, 17, 21, 30, 0, tzinfo=tz)
    target = _today_run_at(now, 22)
    assert _seconds_until(target, now) == 1800.0


def test_startup_catchup_yesterday(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    monkeypatch.setattr(
        "on1y.digest.evening.generate_evening_llm_summary",
        lambda *_a, **_k: (None, "llm_not_configured"),
    )
    from on1y.config import get_settings

    get_settings.cache_clear()
    from on1y.auth.context import user_context
    from on1y.digest.evening import load_evening_digest
    from on1y.digest.evening_auto import _run_startup_catchup

    tz = ZoneInfo("Asia/Shanghai")
    fake_now = datetime(2026, 6, 18, 8, 0, 0, tzinfo=tz)
    with patch("on1y.digest.evening_auto.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.combine = datetime.combine
        _run_startup_catchup()

    with user_context(1):
        assert load_evening_digest(1, "2026-06-17") is not None
    get_settings.cache_clear()
