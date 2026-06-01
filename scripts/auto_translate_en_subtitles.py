#!/usr/bin/env python3
"""Auto-translate English-only YouTube transcripts to Chinese."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.translate.transcript import translate_body_to_zh
from on1y.utils.transcript_meta import classify_transcript, pick_single_transcript

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("auto_translate_en")


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate en-only subtitles to zh")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raw-id", type=int, action="append", dest="raw_ids")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    storage = get_storage()
    conn = storage._connect()
    if args.raw_ids:
        rows = conn.execute(
            "SELECT id, raw_title, body_text, source_meta FROM raw_items WHERE id IN ({})".format(
                ",".join("?" * len(args.raw_ids))
            ),
            args.raw_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, raw_title, body_text, source_meta FROM raw_items WHERE platform = 'youtube'"
        ).fetchall()

    done = 0
    for row in rows:
        if args.limit and done >= args.limit:
            break
        meta = json.loads(row["source_meta"] or "{}")
        if str(meta.get("translated_body_text") or "").strip():
            continue
        body = pick_single_transcript(row["body_text"] or "", prefer_lang="zh")
        if classify_transcript(body, prefer_lang="zh") != "en":
            continue
        raw_id = int(row["id"])
        log.info("translate raw_id=%s %s len=%s", raw_id, (row["raw_title"] or "")[:50], len(body))
        if args.dry_run:
            done += 1
            continue
        translated = translate_body_to_zh(body, title=row["raw_title"])
        meta["translated_body_text"] = translated
        storage.merge_source_meta(raw_id, {"translated_body_text": translated})
        done += 1

    storage.close()
    log.info("Done translated=%s dry_run=%s", done, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
