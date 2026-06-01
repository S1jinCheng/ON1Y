#!/usr/bin/env python3
"""In-place clean VTT/SRT garbage in stored video body_text (YouTube + Bilibili)."""

from __future__ import annotations

import argparse
import logging
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.models.enums import ExtractStatus
from on1y.utils.json_util import loads_meta
from on1y.utils.text_format import format_video_body_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("clean_video_body")


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean stored video transcript bodies")
    parser.add_argument("--platform", choices=("youtube", "bilibili", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    storage = get_storage()
    conn = storage._connect()
    if args.platform == "all":
        rows = conn.execute(
            "SELECT id, platform, raw_title, body_text, extract_status, extract_error, source_meta "
            "FROM raw_items WHERE platform IN ('youtube', 'bilibili')"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, platform, raw_title, body_text, extract_status, extract_error, source_meta "
            "FROM raw_items WHERE platform = ?",
            (args.platform,),
        ).fetchall()

    updated = 0
    for row in rows:
        body = row["body_text"] or ""
        cleaned = format_video_body_text(body)
        new_body = cleaned if cleaned and cleaned != body else body
        status = ExtractStatus(row["extract_status"])
        err = row["extract_error"]
        if row["platform"] == "bilibili" and err == "single_subtitle_lang:zh" and "## 字幕" in new_body:
            status = ExtractStatus.OK
            err = None
        changed = (
            new_body != body
            or status.value != row["extract_status"]
            or (err or None) != (row["extract_error"] or None)
        )
        if not changed:
            continue
        raw_id = int(row["id"])
        if args.dry_run:
            log.info(
                "would update raw_id=%s platform=%s status=%s len %s -> %s",
                raw_id,
                row["platform"],
                status.value,
                len(body),
                len(new_body),
            )
            updated += 1
            continue
        storage.update_raw_item_content(
            raw_id,
            body_text=new_body,
            raw_title=row["raw_title"],
            extract_status=status,
            extract_error=err,
            source_meta=loads_meta(row["source_meta"]),
        )
        updated += 1

    storage.close()
    log.info("Done cleaned=%s dry_run=%s platform=%s", updated, args.dry_run, args.platform)
    return 0


if __name__ == "__main__":
    sys.exit(main())
