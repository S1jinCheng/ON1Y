"""Tests for RSS sync_since filtering."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock, patch

from on1y.ingestion.rss import FeedConfig, _backfill_single_feed, _poll_single_feed


def _published(ts: int) -> str:
    return format_datetime(datetime.fromtimestamp(ts, tz=timezone.utc))


def _feed_entry(*, link: str, entry_id: str, published: str) -> MagicMock:
    """Feedparser-like entry: attribute access plus dict-style ``.get()``."""
    entry = MagicMock()
    entry.link = link
    entry.id = entry_id
    entry.published = published
    entry.get = lambda key, default=None: {
        "link": link,
        "id": entry_id,
        "published": published,
        "title": None,
    }.get(key, default)
    return entry


@patch("on1y.ingestion.rss.parse_feed")
def test_backfill_skips_before_sync_since(mock_parse) -> None:
    sync_since = 1_730_000_000
    mock_parse.return_value = MagicMock(
        bozo=False,
        entries=[
            _feed_entry(
                link="https://example.com/old",
                entry_id="old",
                published=_published(1_700_000_000),
            ),
            _feed_entry(
                link="https://example.com/new",
                entry_id="new",
                published=_published(1_740_000_000),
            ),
        ],
    )
    storage = MagicMock()
    storage.get_raw_by_url.return_value = None
    storage.url_in_rss_queue.return_value = False

    feed = FeedConfig(url="https://example.com/feed", label="yt-test", enabled=True)
    enqueued, skipped = _backfill_single_feed(
        storage,
        feed,
        max_items=10,
        skip_existing=False,
        sync_since_ts=sync_since,
    )
    assert enqueued == 1
    assert skipped == 1


@patch("on1y.ingestion.rss.parse_feed")
def test_poll_incremental_skips_before_sync_since(mock_parse) -> None:
    sync_since = 1_730_000_000
    mock_parse.return_value = MagicMock(
        bozo=False,
        entries=[
            _feed_entry(
                link="https://example.com/new",
                entry_id="new",
                published=_published(1_740_000_000),
            ),
        ],
    )
    storage = MagicMock()
    storage.get_rss_feed_state.return_value = ("prev", _published(1_720_000_000))

    feed = FeedConfig(url="https://example.com/feed", label="zhihu-test", enabled=True)
    enqueued, skipped = _poll_single_feed(storage, feed, sync_since_ts=sync_since)
    assert enqueued == 1
    assert skipped == 0


@patch("on1y.subscriptions.settings.sync_since_timestamp", return_value=1_730_000_000)
@patch("on1y.subscriptions.rss_sync._select_feeds")
@patch("on1y.subscriptions.rss_sync._poll_single_feed", return_value=(2, 1))
def test_sync_rss_subscriptions_report(mock_poll, mock_select, _since) -> None:
    from on1y.subscriptions.rss_sync import sync_rss_subscriptions

    mock_select.return_value = [
        FeedConfig(url="https://a", label="yt-a", enabled=True),
    ]
    storage = MagicMock()
    report = sync_rss_subscriptions(storage, platform="youtube")
    assert report["enqueued"] == 2
    assert report["skipped_before_since"] == 1
    assert report["feeds_matched"] == 1
