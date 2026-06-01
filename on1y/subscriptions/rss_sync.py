"""RSS subscription poll for YouTube / Zhihu feeds (feeds.yaml label prefixes)."""

from __future__ import annotations

import logging
from typing import Any

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.ingestion.rss import (
    _backfill_single_feed,
    _poll_single_feed,
    _select_feeds,
    poll_rss_feeds,
    poll_rss_feeds_backfill,
)
from on1y.ports.storage import StoragePort
from on1y.subscriptions.settings import sync_since_timestamp

logger = logging.getLogger(__name__)

RSS_PLATFORM_PREFIXES: dict[str, str] = {
    "youtube": "yt-",
    "zhihu": "zhihu-",
}


def sync_rss_subscriptions(
    storage: StoragePort,
    *,
    platform: str,
    backfill: bool = False,
    sync_since_ts: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Poll RSS feeds for a platform (youtube / zhihu) by label prefix.
    Respects subscription_settings {platform}_sync_since.
    """
    settings = settings or get_settings()
    label_prefix = RSS_PLATFORM_PREFIXES.get(platform)
    if not label_prefix:
        raise ValueError(f"unsupported RSS subscription platform: {platform}")

    if sync_since_ts is None:
        sync_since_ts = sync_since_timestamp(platform)

    report: dict[str, Any] = {
        "platform": platform,
        "label_prefix": label_prefix,
        "mode": "backfill" if backfill else "poll",
        "sync_since_ts": sync_since_ts,
        "enqueued": 0,
        "skipped_before_since": 0,
        "feeds_matched": 0,
        "skipped_no_feeds": False,
        "errors": [],
    }

    try:
        feeds = _select_feeds(settings.rss_config_path, label_prefix=label_prefix)
    except ConfigurationError:
        report["skipped_no_feeds"] = True
        return report

    report["feeds_matched"] = len(feeds)
    max_items = settings.rss_backfill_max_items_per_feed

    for feed in feeds:
        try:
            if backfill:
                enqueued, skipped = _backfill_single_feed(
                    storage,
                    feed,
                    max_items=max_items,
                    skip_existing=True,
                    sync_since_ts=sync_since_ts,
                )
            else:
                enqueued, skipped = _poll_single_feed(
                    storage,
                    feed,
                    sync_since_ts=sync_since_ts,
                )
            report["enqueued"] += enqueued
            report["skipped_before_since"] += skipped
            logger.info(
                "RSS %s feed %s: enqueued=%s skipped_before_since=%s",
                platform,
                feed.label,
                enqueued,
                skipped,
            )
        except Exception as exc:
            logger.error("RSS feed %s failed: %s", feed.label, exc)
            report["errors"].append({"label": feed.label, "error": str(exc)})

    return report


def poll_rss_platform_batch(
    storage: StoragePort,
    *,
    label_prefix: str,
    backfill: bool = False,
    sync_since_ts: int | None = None,
) -> int:
    """Legacy helper: return enqueued count only."""
    if backfill:
        return poll_rss_feeds_backfill(
            storage,
            label_prefix=label_prefix,
            sync_since_ts=sync_since_ts,
            skip_no_feeds=True,
        )
    return poll_rss_feeds(
        storage,
        label_prefix=label_prefix,
        sync_since_ts=sync_since_ts,
        skip_no_feeds=True,
    )
