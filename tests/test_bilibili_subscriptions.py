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
    assert slug_label("12345", "测试UP") == f"{BILI_UP_FEED_LABEL_PREFIX}12345"
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


@patch("on1y.ingestion.bilibili_subscriptions._enqueue_bilibili_video")
@patch("on1y.subscriptions.settings.sync_since_timestamp", return_value=None)
@patch("on1y.ingestion.bilibili_subscriptions._cookie_jar", return_value={"SESSDATA": "x"})
@patch("on1y.ingestion.bilibili_subscriptions.iter_dynamic_video_feed")
@patch("on1y.ingestion.bilibili_subscriptions.youtube_title_index", return_value={})
def test_poll_bilibili_dynamic_updates(
    _title_index,
    mock_feed,
    _cookie_jar,
    _sync_since,
    mock_enqueue,
) -> None:
    from on1y.ingestion.bilibili_subscriptions import poll_bilibili_dynamic_updates

    mock_feed.return_value = iter(
        [
            {
                "dynamic_id": "dyn1",
                "bvid": "BV1234567891",
                "title": "new",
                "created": 1_740_000_000,
                "up_mid": "42",
                "uname": "UP",
            },
            {
                "dynamic_id": "dyn0",
                "bvid": "BV1234567890",
                "title": "old",
                "created": 1_700_000_000,
                "up_mid": "42",
                "uname": "UP",
            },
        ]
    )
    storage = MagicMock()
    storage.get_rss_feed_state.return_value = (None, None)
    storage.get_raw_by_url.return_value = None
    storage.url_in_rss_queue.return_value = False

    def _fake_enqueue(_storage, *, report, **kwargs) -> None:
        report["enqueued"] += 1

    mock_enqueue.side_effect = _fake_enqueue

    report = poll_bilibili_dynamic_updates(
        storage,
        sync_since_ts=1_730_000_000,
    )
    assert report["mode"] == "dynamic"
    assert report["source"] == "following_dynamics_video"
    assert report["enqueued"] == 1
    assert report["skipped_before_since"] == 1
    mock_feed.assert_called_once()


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
    forward = {
        "type": "DYNAMIC_TYPE_FORWARD",
        "modules": {
            "module_dynamic": {
                "major": {
                    "type": "MAJOR_TYPE_ARCHIVE",
                    "archive": {"bvid": "BV1forward01", "title": "fwd"},
                }
            },
            "module_author": {"mid": "1", "name": "u", "pub_ts": 1_740_000_000},
        },
    }
    assert parse_dynamic_video_item(draw) is None
    assert parse_dynamic_video_item(article) is None
    assert parse_dynamic_video_item(ad) is None
    assert parse_dynamic_video_item(forward) is None


def test_parse_dynamic_video_includes_up_face() -> None:
    from on1y.ingestion.bilibili_api import parse_dynamic_video_item

    item = {
        "type": "DYNAMIC_TYPE_AV",
        "id_str": "dyn1",
        "modules": {
            "module_author": {
                "mid": "42",
                "name": "UP",
                "pub_ts": 1_740_000_000,
                "face": "https://i0.hdslb.com/bfs/face/up.jpg",
            },
            "module_dynamic": {
                "major": {
                    "type": "MAJOR_TYPE_ARCHIVE",
                    "archive": {
                        "bvid": "BV1test0001",
                        "title": "t",
                        "desc": "d",
                        "cover": "https://example.com/cover.jpg",
                        "duration_text": "01:00",
                    },
                }
            },
        },
    }
    parsed = parse_dynamic_video_item(item)
    assert parsed is not None
    assert parsed["up_face"] == "https://i0.hdslb.com/bfs/face/up.jpg"
