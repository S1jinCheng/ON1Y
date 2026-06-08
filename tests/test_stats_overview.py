"""Stats aggregation API helpers."""

from __future__ import annotations

from on1y.auth.context import user_context
from on1y.stats.overview import build_daily_digest, build_stats_overview
from on1y.stats.timezone_util import stats_timezone


def test_stats_timezone_available() -> None:
    tz = stats_timezone()
    assert tz is not None


def test_build_stats_overview(storage, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    from on1y.config import get_settings

    get_settings.cache_clear()
    try:
        with user_context(1):
            view = build_stats_overview(storage, days=30)
        assert view["days"] == 30
        assert "totals" in view
        assert len(view["by_weekday"]) == 7
        assert len(view["by_hour"]) == 24
        daily = build_daily_digest(storage, day=view["end_date"])
        assert daily["date"] == view["end_date"]
    finally:
        get_settings.cache_clear()
