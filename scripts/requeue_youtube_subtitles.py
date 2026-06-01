#!/usr/bin/env python3
"""Re-queue YouTube items whose body_text is description-only or raw VTT garbage."""

from __future__ import annotations

import argparse
import logging
import re
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.pipeline.video_meta import with_subtitle_pending

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("requeue_youtube_subtitles")

VTT_GARBAGE = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>|Kind:\s*captions")


def body_needs_subtitle_refetch(body: str | None) -> bool:
    text = (body or "").strip()
    if not text:
        return True
    has_transcript = any(
        marker in text
        for marker in ("## 字幕", "## Subtitle (English)", "## Transcript")
    )
    if not has_transcript and "## Description" in text:
        return True
    if VTT_GARBAGE.search(text):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-queue bad YouTube subtitle bodies")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    storage = get_storage()
    rows = storage._connect().execute(
        """
        SELECT id, url, body_text, source_meta
        FROM raw_items
        WHERE platform = 'youtube'
        ORDER BY id DESC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()

    queued = 0
    for row in rows:
        if not body_needs_subtitle_refetch(row["body_text"]):
            continue
        raw_id = int(row["id"])
        url = str(row["url"])
        if args.dry_run:
            log.info("would requeue raw_id=%s %s", raw_id, url[:60])
            queued += 1
            continue
        storage.enqueue_subtitle_job(raw_id, url)
        raw = storage.get_raw_by_id(raw_id)
        if raw is None:
            continue
        meta = with_subtitle_pending(raw.source_meta)
        storage.update_raw_item_content(
            raw_id,
            body_text=raw.body_text,
            raw_title=raw.raw_title,
            extract_status=raw.extract_status,
            extract_error="awaiting_subtitles",
            source_meta=meta,
        )
        queued += 1
        log.info("Requeued raw_id=%s", raw_id)

    storage.close()
    log.info("Done queued=%s dry_run=%s", queued, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
