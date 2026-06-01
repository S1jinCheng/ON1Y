#!/usr/bin/env python3
"""Backfill author + avatar into raw_items.source_meta from yt-dlp metadata."""

from __future__ import annotations

import argparse
import logging
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.extract.ytdlp_video import get_ytdlp_video_extractor
from on1y.utils.author_meta import author_meta_patch
from on1y.utils.platform import YTDLP_VIDEO_PLATFORMS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backfill_author")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill author metadata for video items")
    parser.add_argument("--platform", default="youtube", choices=sorted(YTDLP_VIDEO_PLATFORMS))
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()

    storage = get_storage()
    rows = storage._connect().execute(
        """
        SELECT id, url, source_meta FROM raw_items
        WHERE platform = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (args.platform, args.limit),
    ).fetchall()

    extractor = get_ytdlp_video_extractor(args.platform)
    ok = skipped = failed = 0
    for row in rows:
        raw_id = int(row["id"])
        url = str(row["url"])
        try:
            meta = extractor.fetch_metadata(url)
            patch = author_meta_patch(
                author=meta.uploader,
                author_avatar=meta.uploader_avatar,
                author_url=meta.uploader_url,
                cover_image=meta.cover_image,
                channel_id=meta.channel_id,
            )
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
