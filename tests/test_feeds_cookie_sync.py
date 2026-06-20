"""Subscription list must refresh from cookie, not stale feeds.yaml."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from on1y.auth.context import user_context
from on1y.cookies.import_user import persist_user_cookie_payload
from on1y.user.feeds_config import ensure_user_feeds_config, resolve_feeds_config_path
from on1y.user.paths import user_feeds_path


def test_ensure_user_feeds_config_seeds_from_legacy(tmp_path, monkeypatch) -> None:
    from on1y.config import Settings, get_settings

    legacy = tmp_path / "config" / "feeds.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("feeds:\n- url: https://example.com/rss\n  label: legacy\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        db_path=data_dir / "on1y.db",
        rss_config_path=legacy,
    )
    monkeypatch.setattr("on1y.config.get_settings", lambda: settings)
    monkeypatch.setattr("on1y.user.feeds_config.get_settings", lambda: settings)

    with user_context(1):
        path = ensure_user_feeds_config(settings=settings, user_id=1)

    assert path == user_feeds_path(1)
    assert path.is_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["feeds"][0]["label"] == "legacy"
    with user_context(1):
        assert resolve_feeds_config_path(settings=settings) == path


def test_cookie_import_refreshes_youtube_feeds(tmp_path, monkeypatch) -> None:
    from on1y.config import Settings, get_settings

    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        db_path=data_dir / "on1y.db",
        rss_config_path=tmp_path / "config" / "feeds.yaml",
    )
    for mod in (
        "on1y.config",
        "on1y.cookies.verify",
        "on1y.subscriptions.feeds_refresh",
        "on1y.user.feeds_config",
        "on1y.user.paths",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)

    refreshed: list[str] = []

    def fake_refresh(platform: str, *, settings=None, user_id=None):
        refreshed.append(platform)
        return {"platform": platform, "channels_merged": 2}

    monkeypatch.setattr(
        "on1y.subscriptions.feeds_refresh.refresh_subscription_feeds_from_cookie",
        fake_refresh,
    )
    monkeypatch.setattr(
        "on1y.cookies.verify.verify_cookie_account",
        lambda *_a, **_k: {"valid": True, "account_name": "test"},
    )

    payload = {
        "cookies": [
            {"name": "__Secure-1PSID", "value": "x", "domain": ".google.com", "path": "/"},
        ],
        "origins": [],
    }
    with user_context(1):
        result = persist_user_cookie_payload("youtube", payload, user_id=1)

    assert refreshed == ["youtube"]
    assert result["feeds_refresh"]["channels_merged"] == 2
    cookie_path = tmp_path / "data" / "users" / "1" / "cookies" / "youtube.json"
    assert cookie_path.is_file()
    netscape = cookie_path.with_suffix(cookie_path.suffix + ".netscape.txt")
    assert not netscape.is_file()


def test_persist_zlibrary_cookie(tmp_path, monkeypatch) -> None:
    from on1y.config import Settings, get_settings

    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, db_path=data_dir / "on1y.db")
    monkeypatch.setattr("on1y.config.get_settings", lambda: settings)
    monkeypatch.setattr(
        "on1y.cookies.import_user.verify_cookie_account",
        lambda *_a, **_k: {"valid": True, "account_name": "zlib"},
    )

    payload = {
        "cookies": [
            {"name": "remix_userid", "value": "9", "domain": ".z-lib.help", "path": "/"},
            {"name": "remix_userkey", "value": "secret", "domain": ".z-lib.help", "path": "/"},
        ],
        "origins": [],
    }
    with user_context(1):
        result = persist_user_cookie_payload("zlibrary", payload, user_id=1)

    assert result["count"] == 2
    assert (data_dir / "users" / "1" / "cookies" / "zlibrary.json").is_file()
