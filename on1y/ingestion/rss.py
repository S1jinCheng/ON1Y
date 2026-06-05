"""RSS / Atom feed polling via feedparser."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import feedparser
import httpx
import yaml

from on1y.config import get_settings
from on1y.exceptions import ConfigurationError
from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import ExtractStatus, SourceType
from on1y.ports.storage import StoragePort
from on1y.utils.platform import normalize_url
from on1y.utils.youtube_video_filter import should_skip_youtube_url

logger = logging.getLogger(__name__)

USER_AGENT = "On1y/0.1 (+https://github.com/on1y/on1y; RSS poller)"


def _enqueue_feed_entry(
    storage: StoragePort,
    link: str,
    *,
    source: SourceType,
    meta: dict[str, Any],
) -> bool:
    if should_skip_youtube_url(link):
        logger.info("Skipped YouTube feed entry (filtered): %s", link)
        return False
    enqueue_url(storage, link, source=source, source_meta=meta)
    return True


@dataclass(frozen=True)
class FeedConfig:
    url: str
    label: str
    enabled: bool = True


def load_feeds(config_path: Path | None = None) -> list[FeedConfig]:
    settings = get_settings()
    path = config_path or settings.rss_config_path
    if not path.is_file():
        raise ConfigurationError(
            f"RSS config not found: {path}. "
            "Copy config/feeds.yaml.example to config/feeds.yaml"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not raw or "feeds" not in raw:
        raise ConfigurationError(f"Invalid RSS config (missing 'feeds'): {path}")

    feeds: list[FeedConfig] = []
    for entry in raw["feeds"]:
        if not isinstance(entry, dict) or "url" not in entry:
            continue
        feeds.append(
            FeedConfig(
                url=str(entry["url"]),
                label=str(entry.get("label", entry["url"])),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return feeds


def fetch_feed_document(url: str) -> str:
    """Fetch raw RSS/Atom XML with timeout and User-Agent (RSSHub-friendly)."""
    settings = get_settings()
    client_kwargs: dict[str, Any] = {
        "timeout": settings.http_timeout_seconds,
        "follow_redirects": True,
        "headers": {"User-Agent": USER_AGENT},
    }
    if settings.ytdlp_proxy:
        client_kwargs["proxy"] = settings.ytdlp_proxy
    with httpx.Client(**client_kwargs) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def parse_feed(feed: FeedConfig) -> Any:
    """Parse feed from HTTP; fall back to feedparser direct URL fetch."""
    try:
        body = fetch_feed_document(feed.url)
        return feedparser.parse(body)
    except Exception as exc:
        logger.warning("HTTP fetch failed for %s (%s), trying feedparser direct", feed.label, exc)
        return feedparser.parse(feed.url, agent=USER_AGENT)


def poll_rss_feeds(
    storage: StoragePort,
    config_path: Path | None = None,
    *,
    label: str | None = None,
    label_prefix: str | None = None,
    sync_since_ts: int | None = None,
    skip_no_feeds: bool = False,
) -> int:
    """
    Poll enabled feeds and enqueue new entries.
    Returns count of newly enqueued URLs.
    """
    try:
        feeds = _select_feeds(config_path, label=label, label_prefix=label_prefix)
    except ConfigurationError:
        if skip_no_feeds:
            return 0
        raise
    total_new = 0
    for feed in feeds:
        try:
            new_count, _ = _poll_single_feed(storage, feed, sync_since_ts=sync_since_ts)
            total_new += new_count
            logger.info("Feed %s: enqueued %s new item(s)", feed.label, new_count)
        except Exception as exc:
            logger.error("Feed %s failed: %s", feed.label, exc)

    return total_new


def poll_rss_feeds_backfill(
    storage: StoragePort,
    config_path: Path | None = None,
    *,
    label: str | None = None,
    label_prefix: str | None = None,
    max_items_per_feed: int = 100,
    skip_existing: bool = True,
    sync_since_ts: int | None = None,
    skip_no_feeds: bool = False,
) -> int:
    """
    Cold-start: enqueue up to `max_items_per_feed` entries from each matching feed.
    Skips URLs already stored or successfully processed in the queue.
    Sets the feed cursor to the newest entry when done.
    """
    try:
        feeds = _select_feeds(config_path, label=label, label_prefix=label_prefix)
    except ConfigurationError:
        if skip_no_feeds:
            return 0
        raise
    total_new = 0
    for feed in feeds:
        try:
            new_count, _ = _backfill_single_feed(
                storage,
                feed,
                max_items=max_items_per_feed,
                skip_existing=skip_existing,
                sync_since_ts=sync_since_ts,
            )
            total_new += new_count
            logger.info("Feed %s backfill: enqueued %s item(s)", feed.label, new_count)
        except Exception as exc:
            logger.error("Feed %s backfill failed: %s", feed.label, exc)
    return total_new


def _select_feeds(
    config_path: Path | None = None,
    *,
    label: str | None = None,
    label_prefix: str | None = None,
) -> list[FeedConfig]:
    feeds = [f for f in load_feeds(config_path) if f.enabled]
    if label:
        feeds = [f for f in feeds if f.label == label]
    elif label_prefix:
        feeds = [f for f in feeds if f.label.startswith(label_prefix)]
    if not feeds:
        raise ConfigurationError("No enabled feeds matched the filter in config/feeds.yaml")
    return feeds


def list_feed_status(storage: StoragePort, config_path: Path | None = None) -> list[dict[str, Any]]:
    """Return feed config + cursor state for CLI status."""
    rows: list[dict[str, Any]] = []
    for feed in load_feeds(config_path):
        last_id, last_pub = storage.get_rss_feed_state(feed.url)
        rows.append(
            {
                "label": feed.label,
                "url": feed.url,
                "enabled": feed.enabled,
                "last_entry_id": last_id,
                "last_published": last_pub,
            }
        )
    return rows


def reset_feed_cursor(
    storage: StoragePort,
    label: str,
    config_path: Path | None = None,
) -> bool:
    """Clear cursor for a feed by label so next poll re-seeds from latest entry."""
    for feed in load_feeds(config_path):
        if feed.label == label:
            storage.set_rss_feed_state(feed.url, last_entry_id=None, last_published=None)
            logger.info("Reset RSS cursor for feed %s", label)
            return True
    return False


def _poll_single_feed(
    storage: StoragePort,
    feed: FeedConfig,
    *,
    sync_since_ts: int | None = None,
) -> tuple[int, int]:
    parsed = parse_feed(feed)
    if parsed.bozo and not parsed.entries:
        raise ConfigurationError(f"Feed parse error for {feed.url}: {parsed.bozo_exception}")

    last_id, last_published = storage.get_rss_feed_state(feed.url)

    if last_id is None and last_published is None:
        if sync_since_ts is not None:
            settings = get_settings()
            return _backfill_single_feed(
                storage,
                feed,
                max_items=settings.rss_backfill_max_items_per_feed,
                skip_existing=True,
                sync_since_ts=sync_since_ts,
                parsed=parsed,
            )
        enqueued = poll_rss_feeds_initial(storage, feed, parsed=parsed)
        return enqueued, 0

    new_entries: list[Any] = []
    skipped_before_since = 0

    for entry in parsed.entries:
        entry_id = entry.get("id") or entry.get("link")
        if not entry_id:
            continue
        published = _entry_published(entry)
        if _is_before_since(published, sync_since_ts):
            skipped_before_since += 1
            continue
        if _is_newer(entry_id, published, last_id, last_published):
            new_entries.append(entry)

    if not new_entries:
        return 0, skipped_before_since

    new_entries.reverse()
    enqueued = 0
    newest_id: str | None = last_id
    newest_pub: str | None = last_published

    for entry in new_entries:
        link = entry.get("link")
        if not link:
            continue
        entry_id = entry.get("id") or link
        published = _entry_published(entry)
        meta = {
            "feed_url": feed.url,
            "feed_label": feed.label,
            "entry_title": entry.get("title"),
            "entry_id": entry_id,
            "published": published,
        }
        if _enqueue_feed_entry(storage, link, source=SourceType.RSS, meta=meta):
            enqueued += 1
        if _is_newer(entry_id, published, newest_id, newest_pub):
            newest_id = entry_id
            newest_pub = published

    if newest_id:
        storage.set_rss_feed_state(
            feed.url,
            last_entry_id=newest_id,
            last_published=newest_pub,
        )

    return enqueued, skipped_before_since


def _entry_published(entry: Any) -> str | None:
    if hasattr(entry, "published") and entry.published:
        return str(entry.published)
    if hasattr(entry, "updated") and entry.updated:
        return str(entry.updated)
    return None


def _is_newer(
    entry_id: str,
    published: str | None,
    last_id: str | None,
    last_published: str | None,
) -> bool:
    if last_id is None:
        return True

    if published and last_published:
        pub_dt = _parse_feed_date(published)
        last_dt = _parse_feed_date(last_published)
        if pub_dt and last_dt:
            return pub_dt > last_dt

    return entry_id != last_id


def _parse_feed_date(value: str) -> datetime | None:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _is_before_since(published: str | None, sync_since_ts: int | None) -> bool:
    if sync_since_ts is None or not published:
        return False
    pub_dt = _parse_feed_date(published)
    if pub_dt is None:
        return False
    return int(pub_dt.timestamp()) < sync_since_ts


def _backfill_single_feed(
    storage: StoragePort,
    feed: FeedConfig,
    *,
    max_items: int,
    skip_existing: bool,
    sync_since_ts: int | None = None,
    parsed: Any | None = None,
) -> tuple[int, int]:
    parsed = parsed or parse_feed(feed)
    if parsed.bozo and not parsed.entries:
        raise ConfigurationError(f"Feed parse error for {feed.url}: {parsed.bozo_exception}")

    entries = list(parsed.entries[:max_items])
    if not entries:
        return 0, 0

    entries.reverse()
    enqueued = 0
    skipped_before_since = 0
    newest_id: str | None = None
    newest_pub: str | None = None

    for entry in entries:
        link = entry.get("link")
        if not link:
            continue
        entry_id = entry.get("id") or link
        published = _entry_published(entry)
        if _is_before_since(published, sync_since_ts):
            skipped_before_since += 1
            continue
        if skip_existing and _should_skip_backfill_url(storage, link):
            continue
        meta = {
            "feed_url": feed.url,
            "feed_label": feed.label,
            "entry_title": entry.get("title"),
            "entry_id": entry_id,
            "published": published,
            "backfill": True,
        }
        if _enqueue_feed_entry(storage, link, source=SourceType.RSS, meta=meta):
            enqueued += 1
        if _is_newer(entry_id, published, newest_id, newest_pub):
            newest_id = entry_id
            newest_pub = published

    if newest_id:
        storage.set_rss_feed_state(
            feed.url,
            last_entry_id=newest_id,
            last_published=newest_pub,
        )
    return enqueued, skipped_before_since


def _should_skip_backfill_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_url(url)
    raw = storage.get_raw_by_url(normalized)
    if raw is not None and raw.extract_status in (ExtractStatus.OK, ExtractStatus.PARTIAL):
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def poll_rss_feeds_initial(
    storage: StoragePort,
    feed: FeedConfig,
    *,
    parsed: Any | None = None,
) -> int:
    """On first run (no cursor), enqueue only the latest entry."""
    parsed = parsed or parse_feed(feed)
    if not parsed.entries:
        return 0
    entry = parsed.entries[0]
    link = entry.get("link")
    if not link:
        return 0
    entry_id = entry.get("id") or link
    published = _entry_published(entry)
    meta = {
        "feed_url": feed.url,
        "feed_label": feed.label,
        "entry_title": entry.get("title"),
        "entry_id": entry_id,
        "initial_snapshot": True,
    }
    if not _enqueue_feed_entry(storage, link, source=SourceType.RSS, meta=meta):
        return 0
    storage.set_rss_feed_state(feed.url, last_entry_id=entry_id, last_published=published)
    return 1
