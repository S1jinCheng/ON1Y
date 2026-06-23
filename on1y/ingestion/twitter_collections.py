"""Poll X likes and bookmarks via Playwright and enqueue new status URLs."""

from __future__ import annotations

import logging
from typing import Any

from on1y.browser.twitter_playwright import (
    TWITTER_BOOKMARKS_URL,
    TwitterStatusRef,
    discover_twitter_status_refs,
    normalize_twitter_status_url,
    resolve_twitter_account_handle,
    twitter_likes_url,
)
from on1y.config import Settings, get_settings
from on1y.cookies.loader import resolve_cookie_path
from on1y.exceptions import ConfigurationError
from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import SourceType
from on1y.ports.storage import StoragePort

logger = logging.getLogger(__name__)


def _should_skip_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_twitter_status_url(url)
    if storage.get_raw_by_url(normalized) is not None:
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def _enqueue_status_refs(
    storage: StoragePort,
    refs: list[TwitterStatusRef],
    *,
    dry_run: bool,
    feed_label: str,
    folder_name: str,
    early_stop_existing_streak: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "seen": len(refs),
        "enqueued": 0,
        "skipped_existing": 0,
        "dry_run": dry_run,
    }
    existing_streak = 0
    for ref in refs:
        if _should_skip_url(storage, ref.url):
            report["skipped_existing"] += 1
            existing_streak += 1
            if existing_streak >= early_stop_existing_streak:
                report["early_stop"] = True
                break
            continue

        existing_streak = 0
        if dry_run:
            report["enqueued"] += 1
            continue

        title = ref.preview or f"{folder_name} {ref.status_id}"
        enqueue_url(
            storage,
            normalize_twitter_status_url(ref.url),
            source=SourceType.COLLECTION,
            source_meta={
                "platform": "twitter",
                "feed_label": feed_label,
                "entry_title": title[:500],
                "status_id": ref.status_id,
                "folder_name": folder_name,
            },
        )
        report["enqueued"] += 1
    return report


def sync_twitter_likes(
    storage: StoragePort,
    *,
    dry_run: bool = False,
    max_scan: int | None = None,
    early_stop_existing_streak: int | None = None,
    settings: Settings | None = None,
    cookie_path=None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.twitter_likes_sync_enabled:
        return {"name": "likes", "skipped": True, "skip_reason": "disabled"}

    path = cookie_path or resolve_cookie_path("twitter", settings)
    if not path.is_file():
        raise ConfigurationError(f"No X/Twitter cookies at {path}")

    handle = resolve_twitter_account_handle(path, settings=settings)
    if not handle:
        raise ConfigurationError("Cannot resolve X account handle for likes sync")

    scan_cap = max_scan if max_scan is not None else settings.collections_max_items_per_source
    streak_limit = (
        early_stop_existing_streak
        if early_stop_existing_streak is not None
        else settings.collections_early_stop_existing_streak
    )
    likes_url = twitter_likes_url(handle)

    refs = discover_twitter_status_refs(
        path,
        start_url=likes_url,
        max_items=scan_cap,
        max_scrolls=settings.twitter_likes_max_scrolls,
        exclude_retweets=False,
        settings=settings,
    )
    report = _enqueue_status_refs(
        storage,
        refs,
        dry_run=dry_run,
        feed_label="x-likes",
        folder_name="Likes",
        early_stop_existing_streak=streak_limit,
    )
    report["name"] = "likes"
    report["handle"] = handle
    report["start_url"] = likes_url
    return report


def sync_twitter_bookmarks(
    storage: StoragePort,
    *,
    dry_run: bool = False,
    max_scan: int | None = None,
    early_stop_existing_streak: int | None = None,
    settings: Settings | None = None,
    cookie_path=None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.twitter_bookmarks_sync_enabled:
        return {"name": "bookmarks", "skipped": True, "skip_reason": "disabled"}

    path = cookie_path or resolve_cookie_path("twitter", settings)
    if not path.is_file():
        raise ConfigurationError(f"No X/Twitter cookies at {path}")

    scan_cap = max_scan if max_scan is not None else settings.collections_max_items_per_source
    streak_limit = (
        early_stop_existing_streak
        if early_stop_existing_streak is not None
        else settings.collections_early_stop_existing_streak
    )

    refs = discover_twitter_status_refs(
        path,
        start_url=TWITTER_BOOKMARKS_URL,
        max_items=scan_cap,
        max_scrolls=settings.twitter_bookmarks_max_scrolls,
        exclude_retweets=False,
        settings=settings,
    )
    report = _enqueue_status_refs(
        storage,
        refs,
        dry_run=dry_run,
        feed_label="x-bookmarks",
        folder_name="Bookmarks",
        early_stop_existing_streak=streak_limit,
    )
    report["name"] = "bookmarks"
    report["start_url"] = TWITTER_BOOKMARKS_URL
    return report


def sync_twitter_collections(
    storage: StoragePort,
    *,
    include_likes: bool = True,
    include_bookmarks: bool = True,
    dry_run: bool = False,
    max_scan: int | None = None,
    early_stop_existing_streak: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Enqueue new posts from X Likes and/or Bookmarks (likes first)."""
    settings = settings or get_settings()
    path = resolve_cookie_path("twitter", settings)
    report: dict[str, Any] = {
        "platform": "twitter",
        "sources": [],
        "enqueued": 0,
        "skipped_existing": 0,
    }

    selected: list[str] = []
    if include_likes and settings.twitter_likes_sync_enabled:
        selected.append("likes")
    if include_bookmarks and settings.twitter_bookmarks_sync_enabled:
        selected.append("bookmarks")

    if not selected:
        report["skipped"] = True
        report["skip_reason"] = "disabled"
        return report

    for name in selected:
        try:
            if name == "likes":
                source_report = sync_twitter_likes(
                    storage,
                    dry_run=dry_run,
                    max_scan=max_scan,
                    early_stop_existing_streak=early_stop_existing_streak,
                    settings=settings,
                    cookie_path=path,
                )
            else:
                source_report = sync_twitter_bookmarks(
                    storage,
                    dry_run=dry_run,
                    max_scan=max_scan,
                    early_stop_existing_streak=early_stop_existing_streak,
                    settings=settings,
                    cookie_path=path,
                )
            report["sources"].append(source_report)
            report["enqueued"] += int(source_report.get("enqueued") or 0)
            report["skipped_existing"] += int(source_report.get("skipped_existing") or 0)
        except ConfigurationError as exc:
            logger.warning("X %s sync skipped: %s", name, exc)
            report["sources"].append({"name": name, "error": str(exc), "cookie_error": True})

    failed = [s for s in report["sources"] if s.get("cookie_error") or s.get("error")]
    if failed and report["enqueued"] == 0 and len(failed) == len(report["sources"]):
        report["cookie_error"] = True
        report["error"] = str(failed[0].get("error") or "X collections sync failed")

    return report
