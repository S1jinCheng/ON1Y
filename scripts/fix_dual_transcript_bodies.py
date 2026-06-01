#!/usr/bin/env python3
"""Fix stored YouTube bodies that contain both zh and en transcript sections."""

from __future__ import annotations

import argparse
import logging
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.models.enums import ExtractStatus
from on1y.utils.json_util import loads_meta
from on1y.config import get_settings
from on1y.utils.transcript_meta import body_has_dual_transcripts, pick_single_transcript

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("fix_dual_transcripts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep one transcript language in stored bodies")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raw-id", type=int, action="append", dest="raw_ids")
    args = parser.parse_args()

    settings = get_settings()
    storage = get_storage()
    conn = storage._connect()
    if args.raw_ids:
        rows = conn.execute(
            "SELECT id, raw_title, body_text, extract_status, extract_error, source_meta "
            "FROM raw_items WHERE id IN ({})".format(",".join("?" * len(args.raw_ids))),
            args.raw_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, raw_title, body_text, extract_status, extract_error, source_meta "
            "FROM raw_items WHERE platform = 'youtube'"
        ).fetchall()

    updated = 0
    for row in rows:
        body = row["body_text"] or ""
        if not body_has_dual_transcripts(body):
            continue
        cleaned = pick_single_transcript(body, prefer_lang=settings.content_locale)
        if cleaned == body:
            continue
        raw_id = int(row["id"])
        log.info(
            "raw_id=%s %s len %s -> %s",
            raw_id,
            (row["raw_title"] or "")[:50],
            len(body),
            len(cleaned),
        )
        if args.dry_run:
            updated += 1
            continue
        status = row["extract_status"] or ExtractStatus.OK.value
        try:
            extract_status = ExtractStatus(status)
        except ValueError:
            extract_status = ExtractStatus.OK
        storage.update_raw_item_content(
            raw_id,
            body_text=cleaned,
            raw_title=row["raw_title"],
            extract_status=extract_status,
            extract_error=row["extract_error"],
            source_meta=loads_meta(row["source_meta"]),
        )
        updated += 1

    storage.close()
    log.info("Done updated=%s dry_run=%s", updated, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
