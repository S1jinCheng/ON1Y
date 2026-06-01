#!/usr/bin/env python3
"""Backfill author, avatar, and cover into raw_items.source_meta."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.pipeline.video_author import enrich_video_source_meta
from on1y.utils.author_meta import resolve_author_avatar
from on1y.utils.platform import YTDLP_VIDEO_PLATFORMS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backfill_author")

_META_KEYS = ("author", "author_avatar", "author_url", "cover_image", "channel_id")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill author metadata for video items")
    parser.add_argument("--platform", default="bilibili", choices=sorted(YTDLP_VIDEO_PLATFORMS))
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--missing-only", action="store_true", default=True)
    args = parser.parse_args()

    storage = get_storage()
    rows = storage._connect().execute(
        """
        SELECT id, url, source_meta FROM raw_items
        WHERE platform = ? AND deleted_at IS NULL
        ORDER BY id DESC
        LIMIT ?
        """,
        (args.platform, args.limit),
    ).fetchall()

    ok = skipped = failed = 0
    for row in rows:
        raw_id = int(row["id"])
        url = str(row["url"])
        try:
            base = json.loads(row["source_meta"] or "{}")
            if args.missing_only and resolve_author_avatar(base):
                skipped += 1
                continue
            enriched = enrich_video_source_meta(base, platform=args.platform, url=url)
            patch = {
                key: enriched[key]
                for key in _META_KEYS
                if str(enriched.get(key) or "").strip()
                and str(enriched.get(key) or "").strip() != str(base.get(key) or "").strip()
            }
            if not patch:
                skipped += 1
                continue
            storage.merge_source_meta(raw_id, patch)
            ok += 1
            if ok % 20 == 0:
                log.info("Updated %s items...", ok)
        except Exception as exc:
            failed += 1
            log.warning("raw_id=%s failed: %s", raw_id, exc)

    storage.close()
    log.info("Done ok=%s skipped=%s failed=%s", ok, skipped, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
