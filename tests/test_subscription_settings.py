"""Tests for subscription sync settings."""

from __future__ import annotations

from datetime import date

from on1y.subscriptions.settings import (
    load_subscription_settings,
    public_settings_view,
    save_subscription_settings,
    sync_since_date,
    sync_since_timestamp,
)


def test_save_and_load_subscription_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    save_subscription_settings(bilibili_sync_since="2025-03-15")
    cfg = load_subscription_settings()
    assert cfg["bilibili_sync_since"] == "2025-03-15"
    assert cfg["youtube_sync_since"] is None

    view = public_settings_view()
    assert view["bilibili_sync_since"] == "2025-03-15"
    assert view["platforms"] == ["bilibili", "youtube", "zhihu"]

    assert sync_since_date("bilibili") == date(2025, 3, 15)
    assert sync_since_timestamp("bilibili") == 1_741_996_800
