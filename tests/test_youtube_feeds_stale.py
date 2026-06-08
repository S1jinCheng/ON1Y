"""YouTube feeds refresh when cookie is newer than feeds.yaml."""

from __future__ import annotations

from pathlib import Path

from on1y.subscriptions.feeds_refresh import youtube_feeds_stale


def test_youtube_feeds_stale_when_feeds_missing(tmp_path: Path, monkeypatch) -> None:
    cookie = tmp_path / "youtube.json"
    cookie.write_text('{"cookies":[]}', encoding="utf-8")
    feeds = tmp_path / "feeds.yaml"

    monkeypatch.setattr(
        "on1y.cookies.loader.resolve_cookie_path",
        lambda *a, **k: cookie,
    )
    monkeypatch.setattr(
        "on1y.user.feeds_config.resolve_feeds_config_path",
        lambda *a, **k: feeds,
    )

    assert youtube_feeds_stale() is True
