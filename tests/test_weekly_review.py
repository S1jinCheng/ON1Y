"""Weekly review aggregation."""

from __future__ import annotations

from datetime import date, datetime

from on1y.auth.context import user_context
from on1y.stats.weekly import build_weekly_review, week_range_containing, week_range_for_offset


def test_week_range_monday_sunday() -> None:
    start, end = week_range_containing(date(2026, 6, 5))  # Friday
    assert start == date(2026, 6, 1)
    assert end == date(2026, 6, 7)


def test_week_offset_zero_is_current_week() -> None:
    from on1y.stats.timezone_util import stats_timezone

    start, end = week_range_for_offset(0)
    local_today = datetime.now(stats_timezone()).date()
    assert start <= local_today <= end


def test_build_weekly_review(storage, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    from on1y.config import get_settings

    get_settings.cache_clear()
    try:
        with user_context(1):
            view = build_weekly_review(storage, week_offset=0)
        assert view["week_offset"] == 0
        assert "reading" in view
        assert "notes" in view
        assert len(view["reading"]["daily"]) == 7
        assert view["comparison"]["published_delta"] == (
            view["reading"]["published_total"] - view["comparison"]["published_prev_week"]
        )
    finally:
        get_settings.cache_clear()
