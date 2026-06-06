"""Sync YouTube account playlists (Watch Later, Liked) into pending_urls."""

from __future__ import annotations

import logging
from typing import Any

import yt_dlp

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.extract.ytdlp_util import build_ytdlp_opts
from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import ExtractStatus, SourceType
from on1y.ports.storage import StoragePort
from on1y.utils.platform import normalize_url
from on1y.utils.youtube_video_filter import should_skip_youtube_url

logger = logging.getLogger(__name__)

SYSTEM_PLAYLISTS: dict[str, tuple[str, str]] = {
    "watch_later": ("WL", "youtube-watch-later"),
    "liked": ("LL", "youtube-liked"),
}


def _should_skip_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_url(url)
    raw = storage.get_raw_by_url(normalized)
    if raw is not None and raw.extract_status in (ExtractStatus.OK, ExtractStatus.PARTIAL):
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def _video_url_from_entry(entry: dict[str, Any]) -> str | None:
    video_id = str(entry.get("id") or "").strip()
    if not video_id or video_id.startswith("PL"):
        return None
    url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
    if url and "watch" in url:
        return normalize_url(url)
    return normalize_url(f"https://www.youtube.com/watch?v={video_id}")


def fetch_playlist_entries(
    playlist_list_id: str,
    *,
    max_items: int,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    url = f"https://www.youtube.com/playlist?list={playlist_list_id}"
    opts = build_ytdlp_opts(
        cookie_path=settings.youtube_cookies_path,
        cookies_required=True,
        ignore_no_formats_error=True,
        extract_flat="in_playlist",
        playlistend=max(1, max_items),
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        msg = str(exc)
        if "login" in msg.lower() or "private" in msg.lower() or "cookie" in msg.lower():
            raise ConfigurationError(
                f"YouTube playlist {playlist_list_id} requires valid cookies: {msg}"
            ) from exc
        raise ConfigurationError(f"YouTube playlist fetch failed: {msg}") from exc

    if not isinstance(info, dict):
        return []
    entries = info.get("entries") or []
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict):
            rows.append(entry)
    return rows


def sync_youtube_collections(
    storage: StoragePort,
    *,
    include_watch_later: bool = True,
    include_liked: bool = True,
    max_items_per_playlist: int = 80,
    early_stop_existing_streak: int = 20,
    dry_run: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Enqueue new videos from Watch Later / Liked playlists (newest first)."""
    settings = settings or get_settings()
    selected: list[tuple[str, str, str]] = []
    if include_watch_later:
        list_id, label = SYSTEM_PLAYLISTS["watch_later"]
        selected.append(("watch_later", list_id, label))
    if include_liked:
        list_id, label = SYSTEM_PLAYLISTS["liked"]
        selected.append(("liked", list_id, label))

    report: dict[str, Any] = {
        "playlists": [],
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_filtered": 0,
        "unique_urls": 0,
    }
    seen_urls: set[str] = set()

    for playlist_name, list_id, feed_label in selected:
        try:
            entries = fetch_playlist_entries(list_id, max_items=max_items_per_playlist, settings=settings)
        except ConfigurationError as exc:
            # Watch Later (WL) is often unavailable via yt-dlp even with valid cookies.
            logger.warning("YouTube %s skipped: %s", playlist_name, exc)
            report["playlists"].append(
                {
                    "name": playlist_name,
                    "list_id": list_id,
                    "error": str(exc),
                    "scanned": 0,
                    "enqueued": 0,
                }
            )
            continue
        coll_stats = {
            "name": playlist_name,
            "list_id": list_id,
            "scanned": 0,
            "enqueued": 0,
            "skipped_existing": 0,
            "skipped_filtered": 0,
            "stopped_early": False,
        }
        existing_streak = 0

        for entry in entries:
            coll_stats["scanned"] += 1
            url = _video_url_from_entry(entry)
            if not url:
                continue
            if should_skip_youtube_url(url):
                coll_stats["skipped_filtered"] += 1
                report["skipped_filtered"] += 1
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            if _should_skip_url(storage, url):
                coll_stats["skipped_existing"] += 1
                report["skipped_existing"] += 1
                existing_streak += 1
                if existing_streak >= early_stop_existing_streak:
                    coll_stats["stopped_early"] = True
                    break
                continue

            existing_streak = 0
            if dry_run:
                coll_stats["enqueued"] += 1
                report["enqueued"] += 1
                continue

            meta = {
                "feed_label": feed_label,
                "playlist_id": list_id,
                "playlist_name": playlist_name,
                "entry_title": entry.get("title"),
                "source": "youtube_playlist_api",
            }
            enqueue_url(storage, url, source=SourceType.RSS, source_meta=meta)
            coll_stats["enqueued"] += 1
            report["enqueued"] += 1

        logger.info(
            "YouTube %s: scanned=%s enqueued=%s skip=%s early=%s",
            playlist_name,
            coll_stats["scanned"],
            coll_stats["enqueued"],
            coll_stats["skipped_existing"],
            coll_stats["stopped_early"],
        )
        report["playlists"].append(coll_stats)

    report["unique_urls"] = len(seen_urls)
    report["queue_pending"] = (
        storage.count_pending_for_platform("youtube")
        if hasattr(storage, "count_pending_for_platform")
        else None
    )
    return report
