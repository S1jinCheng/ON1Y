#!/usr/bin/env python3
"""Delete ingested YouTube live streams (and live replays) from the database."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import yt_dlp

from on1y.adapters.sqlite_storage import get_storage
from on1y.config import get_settings
from on1y.extract.ytdlp_meta import video_metadata_from_info
from on1y.extract.ytdlp_util import build_ytdlp_opts
from on1y.utils.youtube_video_filter import (
    is_youtube_live_url,
    youtube_ingest_reject_reason,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("delete_youtube_live")

_LIVE_TITLE = re.compile(
    r"(?:\bLIVE\b|直播|正在直播|live\s*stream|stream\s*live|【直播|直播回放|直播切片|\[直播)",
    re.I,
)


def _fetch_info(url: str) -> dict | None:
    settings = get_settings()
    opts = build_ytdlp_opts(
        cookie_path=settings.youtube_cookies_path,
        ignore_no_formats_error=True,
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info if isinstance(info, dict) else None
    except Exception as exc:
        log.warning("metadata failed url=%s: %s", url, exc)
        return None


def _classify_row(row: dict, *, live_only: bool) -> tuple[int, str, str, str] | None:
    raw_id = int(row["id"])
    url = str(row["url"] or "")
    title = str(row["raw_title"] or "")

    if is_youtube_live_url(url):
        return raw_id, url, title, "youtube_live_url"
    if _LIVE_TITLE.search(title):
        return raw_id, url, title, "youtube_title"

    info = _fetch_info(url)
    if info is None:
        return None
    meta = video_metadata_from_info(info)
    settings = get_settings()
    if live_only:
        if meta.is_live or (meta.live_status in {"is_live", "is_upcoming"}):
            return raw_id, url, title, "youtube_live"
        return None
    reason = youtube_ingest_reject_reason(url, meta, settings)
    if reason in {"youtube_live", "youtube_live_replay"}:
        return raw_id, url, title, reason
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete YouTube live stream items from On1y DB")
    parser.add_argument("--dry-run", action="store_true", help="List matches without deleting")
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Delete only active/upcoming live streams, keep live replays",
    )
    parser.add_argument("--workers", type=int, default=6, help="Parallel yt-dlp workers")
    parser.add_argument("--limit", type=int, default=0, help="Max items to check (0 = all)")
    args = parser.parse_args()

    storage = get_storage()
    rows = [
        dict(row)
        for row in storage._connect().execute(
            """
            SELECT id, url, raw_title
            FROM raw_items
            WHERE platform = 'youtube' AND deleted_at IS NULL
            ORDER BY id ASC
            """
        ).fetchall()
    ]
    if args.limit > 0:
        rows = rows[: args.limit]

    log.info("Checking %s YouTube item(s) with %s workers...", len(rows), args.workers)
    to_delete: list[tuple[int, str, str, str]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(_classify_row, row, live_only=args.live_only): row for row in rows
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            if done % 25 == 0:
                log.info("Progress %s/%s", done, len(rows))
            match = future.result()
            if match:
                to_delete.append(match)

    to_delete.sort(key=lambda item: item[0])
    log.info("Matched %s live item(s)", len(to_delete))
    for raw_id, url, title, reason in to_delete:
        log.info("[%s] %s | %s", reason, raw_id, title[:80])

    if args.dry_run:
        log.info("Dry run — no deletions")
        storage.close()
        return 0

    deleted = 0
    for raw_id, _url, _title, _reason in to_delete:
        storage.delete_raw_item(raw_id)
        deleted += 1

    storage.close()
    log.info("Deleted %s item(s)", deleted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
