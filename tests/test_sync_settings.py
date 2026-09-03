"""Per-user sync tuning (sync_settings.json)."""

from __future__ import annotations

from on1y.auth.context import user_context
from on1y.sync_settings.settings import (
    load_sync_prefs,
    public_settings_view,
    resolve_settings,
    save_sync_settings,
    settings_file_path,
)


def test_save_clamps_and_resolve(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    with user_context(1):
        save_sync_settings(
            zhihu_api_poll_max_followees=999,
            zhihu_api_poll_max_pages=0,
            auto_sync_interval_minutes=2,
            zhihu_follow_sync_mode="api",
        )
        prefs = load_sync_prefs()
        assert prefs["zhihu_api_poll_max_followees"] == 200
        assert prefs["zhihu_api_poll_max_pages"] == 1
        assert prefs["auto_sync_interval_minutes"] == 5
        assert prefs["zhihu_follow_sync_mode"] == "api"

        view = public_settings_view()
        assert view["zhihu_api_poll_max_followees"] == 200
        assert view["user_overrides"]["zhihu_api_poll_max_followees"] == 200

        resolved = resolve_settings()
        assert resolved.zhihu_api_poll_max_followees == 200
        assert resolved.zhihu_follow_sync_mode == "api"
        assert settings_file_path().is_file()


def test_invalid_mode_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    with user_context(1):
        save_sync_settings(zhihu_follow_sync_mode="bogus")
        assert "zhihu_follow_sync_mode" not in load_sync_prefs()

        save_sync_settings(zhihu_follow_sync_mode="rss")
        assert load_sync_prefs()["zhihu_follow_sync_mode"] == "rss"


def test_bilibili_and_alert_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    with user_context(1):
        save_sync_settings(
            bilibili_up_poll_mode="dynamic",
            bilibili_dynamic_poll_max_pages=8,
            bilibili_up_poll_rate_limit_backoff_seconds=999,
            alert_cooldown_seconds=30,
            economist_github_raw_base="https://mirror.example/raw",
        )
        prefs = load_sync_prefs()
        assert prefs["bilibili_dynamic_poll_max_pages"] == 8
        assert prefs["bilibili_up_poll_rate_limit_backoff_seconds"] == 600.0
        assert prefs["alert_cooldown_seconds"] == 60.0

        view = public_settings_view()
        assert view["economist_github_raw_base"] == "https://mirror.example/raw"
        assert resolve_settings().bilibili_dynamic_poll_max_pages == 8


def test_collection_platforms_are_normalized_and_user_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    with user_context(1):
        save_sync_settings(collections_sync_platforms=" youtube, bad, bilibili, youtube ")
        prefs = load_sync_prefs()
        assert prefs["collections_sync_platforms"] == "youtube,bilibili"
        assert resolve_settings().collections_sync_platforms == "youtube,bilibili"
