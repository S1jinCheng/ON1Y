"""Poll X home timeline via Playwright and enqueue new status URLs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from on1y.browser.twitter_playwright import (
    TWITTER_HOME_URL,
    discover_twitter_status_refs,
    normalize_twitter_status_url,
)
from on1y.config import Settings, get_settings
from on1y.cookies.loader import resolve_cookie_path
from on1y.exceptions import ConfigurationError
from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import SourceType
from on1y.ports.storage import StoragePort

logger = logging.getLogger(__name__)

HOME_TIMELINE_CURSOR_KEY = "twitter-home-timeline"


def home_timeline_cursor_key() -> str:
    return HOME_TIMELINE_CURSOR_KEY


def _should_skip_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_twitter_status_url(url)
    if storage.get_raw_by_url(normalized) is not None:
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def _published_ts(iso_value: str | None) -> int | None:
    if not iso_value:
        return None
    text = iso_value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


def poll_twitter_home_timeline(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    backfill: bool = False,
    sync_since_ts: int | None = None,
    backfill_max_days: int | None = None,
) -> dict[str, Any]:
    """Discover new posts from the authenticated home timeline."""
    settings = settings or get_settings()
    if not settings.twitter_sync_enabled:
        return {"platform": "twitter", "skipped": True, "skip_reason": "disabled"}

    from on1y.subscriptions.settings import resolve_sync_since_ts

    sync_since_ts = resolve_sync_since_ts(
        "twitter",
        sync_since_ts=sync_since_ts,
        backfill=backfill,
        backfill_max_days=backfill_max_days,
    )

    path = resolve_cookie_path("twitter", settings)
    if not path.is_file():
        raise ConfigurationError(f"No X/Twitter cookies at {path}")

    cursor_key = home_timeline_cursor_key()
    last_id, _ = storage.get_rss_feed_state(cursor_key)
    first_run = last_id is None

    max_items = settings.twitter_poll_max_items
    if backfill or (sync_since_ts is not None and first_run):
        max_items = max(max_items, settings.twitter_poll_backfill_max_items)

    report: dict[str, Any] = {
        "platform": "twitter",
        "mode": "home_following" if settings.twitter_home_following_only else "home_timeline",
        "max_items": max_items,
        "seen": 0,
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_before_since": 0,
        "skipped_retweets": 0,
        "skipped_cursor": 0,
        "caught_up": False,
        "sync_since_ts": sync_since_ts,
        "errors": [],
    }

    try:
        refs = discover_twitter_status_refs(
            path,
            start_url=TWITTER_HOME_URL,
            max_items=max_items,
            max_scrolls=settings.twitter_poll_max_scrolls,
            exclude_retweets=settings.twitter_exclude_retweets,
            following_tab=settings.twitter_home_following_only,
            settings=settings,
        )
    except ConfigurationError as exc:
        report["errors"].append(str(exc))
        report["following_tab_failed"] = True
        logger.warning("X home Following feed unavailable: %s", exc)
        return report
    report["seen"] = len(refs)

    newest_id = last_id
    from on1y.sync.progress import get_cold_start_progress

    progress = get_cold_start_progress()

    for ref in refs:
        if (
            not backfill
            and not first_run
            and last_id
            and ref.status_id == last_id
        ):
            report["caught_up"] = True
            break

        if (
            not backfill
            and not first_run
            and last_id
            and ref.status_id.isdigit()
            and last_id.isdigit()
            and int(ref.status_id) <= int(last_id)
        ):
            report["skipped_cursor"] += 1
            continue

        published_ts = _published_ts(ref.published)
        if (
            sync_since_ts is not None
            and published_ts is not None
            and published_ts < sync_since_ts
        ):
            report["skipped_before_since"] += 1
            continue

        if _should_skip_url(storage, ref.url):
            report["skipped_existing"] += 1
            continue

        title = ref.preview or f"Post {ref.status_id}"
        enqueue_url(
            storage,
            normalize_twitter_status_url(ref.url),
            source=SourceType.RSS,
            source_meta={
                "platform": "twitter",
                "feed_label": "x-home",
                "entry_title": title[:500],
                "published": published_ts,
                "status_id": ref.status_id,
            },
        )
        report["enqueued"] += 1
        progress and progress.log_item(
            phase="subscriptions",
            title=title[:120],
            platform="twitter",
            status="enqueued",
            url=ref.url,
            detail="home timeline",
        )

        if newest_id is None or int(ref.status_id) > int(newest_id):
            newest_id = ref.status_id

    if newest_id and newest_id != last_id:
        storage.set_rss_feed_state(
            cursor_key,
            last_entry_id=newest_id,
            last_published=None,
        )

    return report


def sync_twitter_subscriptions(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    poll: bool = True,
    backfill: bool = False,
    sync_since_ts: int | None = None,
    backfill_max_days: int | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {"platform": "twitter"}
    if not poll:
        report["poll"] = {"skipped": True, "skip_reason": "poll_disabled"}
        return report
    report["poll"] = poll_twitter_home_timeline(
        storage,
        settings=settings,
        backfill=backfill,
        sync_since_ts=sync_since_ts,
        backfill_max_days=backfill_max_days,
    )
    return report
