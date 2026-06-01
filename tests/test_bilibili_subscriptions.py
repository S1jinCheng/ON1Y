"""Tests for Bilibili UP subscription sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from on1y.ingestion.bilibili_feeds import (
    BILI_UP_FEED_LABEL_PREFIX,
    build_feed_url,
    merge_bilibili_up_feeds_yaml,
    slug_label,
    up_cursor_key,
)
from on1y.ingestion.bilibili_subscriptions import poll_bilibili_up_updates


def test_slug_label_and_cursor() -> None:
    assert slug_label("12345", "测试UP").startswith(BILI_UP_FEED_LABEL_PREFIX)
    assert up_cursor_key("12345") == "bilibili-up://12345"
    assert build_feed_url("https://rsshub.app", "12345") == (
        "https://rsshub.app/bilibili/user/video/12345"
    )


def test_merge_bilibili_up_feeds_yaml(tmp_path: Path) -> None:
    feeds_path = tmp_path / "feeds.yaml"
    feeds_path.write_text(
        yaml.safe_dump(
            {
                "feeds": [
                    {"url": "https://example.com/rss", "label": "misc", "enabled": True},
                    {"url": "https://old/up", "label": "bili-up-old", "enabled": True},
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    count = merge_bilibili_up_feeds_yaml(
        [{"mid": "42", "uname": "Alice"}],
        feeds_path=feeds_path,
        rsshub_base="https://rsshub.app",
        enabled=True,
        dry_run=False,
    )
    assert count == 1
    data = yaml.safe_load(feeds_path.read_text(encoding="utf-8"))
    labels = [f["label"] for f in data["feeds"]]
    assert "misc" in labels
    assert "bili-up-old" not in labels
    assert any(str(label).startswith(BILI_UP_FEED_LABEL_PREFIX) for label in labels)


@patch("on1y.subscriptions.settings.sync_since_timestamp", return_value=None)
@patch("on1y.ingestion.bilibili_subscriptions._cookie_jar", return_value={"SESSDATA": "x"})
@patch("on1y.ingestion.bilibili_subscriptions.iter_up_recent_videos")
@patch("on1y.ingestion.bilibili_subscriptions.fetch_bilibili_followings")
@patch("on1y.ingestion.bilibili_subscriptions.youtube_title_index", return_value={})
def test_poll_bilibili_up_with_sync_since(
    _title_index,
    mock_followings,
    mock_videos,
    _cookie_jar,
    _sync_since,
) -> None:
    mock_followings.return_value = [{"mid": "99", "uname": "Bob"}]
    mock_videos.return_value = iter(
        [
            {"bvid": "BV1xx4111new", "title": "new", "created": 1_740_000_000},
            {"bvid": "BV1xx4111old", "title": "old", "created": 1_700_000_000},
        ]
    )

    storage = MagicMock()
    storage.get_rss_feed_state.return_value = (None, None)
    storage.get_raw_by_url.return_value = None
    storage.url_in_rss_queue.return_value = False

    report = poll_bilibili_up_updates(
        storage,
        followings=mock_followings.return_value,
        sync_since_ts=1_730_000_000,
    )
    assert report["enqueued"] == 1
    assert report["skipped_before_since"] == 1


@patch("on1y.subscriptions.settings.sync_since_timestamp", return_value=None)
@patch("on1y.ingestion.bilibili_subscriptions._cookie_jar", return_value={"SESSDATA": "x"})
@patch("on1y.ingestion.bilibili_subscriptions.iter_up_recent_videos")
@patch("on1y.ingestion.bilibili_subscriptions.fetch_bilibili_followings")
@patch("on1y.ingestion.bilibili_subscriptions.youtube_title_index", return_value={})
def test_poll_bilibili_up_initial_snapshot(
    _title_index,
    mock_followings,
    mock_videos,
    _cookie_jar,
    _sync_since,
) -> None:
    mock_followings.return_value = [{"mid": "99", "uname": "Bob"}]
    mock_videos.return_value = iter(
        [
            {
                "bvid": "BV1xx4111xxx",
                "title": "hello",
                "created": 1_700_000_000,
            }
        ]
    )

    storage = MagicMock()
    storage.get_rss_feed_state.return_value = (None, None)
    storage.get_raw_by_url.return_value = None
    storage.url_in_rss_queue.return_value = False

    report = poll_bilibili_up_updates(storage, followings=mock_followings.return_value)
    assert report["enqueued"] == 1
    storage.enqueue.assert_called()
    storage.set_rss_feed_state.assert_called()


def test_sync_bilibili_subscriptions_skipped_when_disabled() -> None:
    from on1y.config import Settings
    from on1y.ingestion.bilibili_subscriptions import sync_bilibili_subscriptions

    storage = MagicMock()
    settings = Settings(bilibili_up_sync_enabled=False)
    report = sync_bilibili_subscriptions(storage, settings=settings, sync_config=False, poll=True)
    assert report["skipped"] is True
    assert report["skip_reason"] == "bilibili_up_sync_disabled"
    storage.enqueue.assert_not_called()


@patch("on1y.subscriptions.settings.sync_since_timestamp", return_value=None)
@patch("on1y.ingestion.bilibili_subscriptions._cookie_jar", return_value={"SESSDATA": "x"})
@patch("on1y.ingestion.bilibili_subscriptions.iter_dynamic_video_feed")
@patch("on1y.ingestion.bilibili_subscriptions.youtube_title_index", return_value={})
def test_poll_bilibili_dynamic_updates(
    _title_index,
    mock_dynamic,
    _cookie_jar,
    _sync_since,
) -> None:
    from on1y.ingestion.bilibili_subscriptions import poll_bilibili_dynamic_updates

    mock_dynamic.return_value = iter(
        [
            {
                "dynamic_id": "dyn-new",
                "bvid": "BV1xx4111new",
                "title": "new",
                "created": 1_740_000_000,
                "description": "desc",
                "pic": "http://example.com/cover.jpg",
                "up_mid": "99",
                "uname": "Bob",
                "duration_sec": 120,
            },
            {
                "dynamic_id": "dyn-old",
                "bvid": "BV1xx4111old",
                "title": "old",
                "created": 1_700_000_000,
                "description": "desc",
                "pic": "http://example.com/cover.jpg",
                "up_mid": "99",
                "uname": "Bob",
                "duration_sec": 120,
            },
        ]
    )

    storage = MagicMock()
    storage.get_rss_feed_state.return_value = (None, None)
    storage.get_raw_by_url.return_value = None
    storage.url_in_rss_queue.return_value = False

    report = poll_bilibili_dynamic_updates(
        storage,
        sync_since_ts=1_730_000_000,
    )
    assert report["mode"] == "dynamic"
    assert report["enqueued"] == 1
    assert report["skipped_before_since"] == 1
    storage.set_rss_feed_state.assert_called()


def test_parse_dynamic_video_rejects_draw_and_article() -> None:
    from on1y.ingestion.bilibili_api import parse_dynamic_video_item

    draw = {
        "type": "DYNAMIC_TYPE_DRAW",
        "modules": {
            "module_dynamic": {"major": {"type": "MAJOR_TYPE_DRAW", "draw": {"items": []}}},
            "module_author": {"mid": "1", "name": "u", "pub_ts": 1_740_000_000},
        },
    }
    article = {
        "type": "DYNAMIC_TYPE_ARTICLE",
        "modules": {
            "module_dynamic": {"major": {"type": "MAJOR_TYPE_ARTICLE", "article": {"title": "x"}}},
            "module_author": {"mid": "1", "name": "u", "pub_ts": 1_740_000_000},
        },
    }
    ad = {
        "type": "DYNAMIC_TYPE_AV",
        "modules": {
            "module_dynamic": {"major": {"type": "MAJOR_TYPE_COMMON", "common": {"title": "ad"}}},
            "module_author": {"mid": "1", "name": "u", "pub_ts": 1_740_000_000},
        },
    }
    assert parse_dynamic_video_item(draw) is None
    assert parse_dynamic_video_item(article) is None
    assert parse_dynamic_video_item(ad) is None
