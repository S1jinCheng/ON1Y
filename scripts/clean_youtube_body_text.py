#!/usr/bin/env python3
"""Clean VTT garbage in stored YouTube body_text without re-downloading."""

from __future__ import annotations

import argparse
import logging
import re
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.extract.subtitles import strip_subtitle_markup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("clean_youtube_body")

VTT_GARBAGE = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>|Kind:\s*captions")
SECTION_MARKERS = ("## 字幕", "## Subtitle", "## Transcript")


def _extract_title_and_sections(body: str) -> tuple[str, str, str]:
    title = ""
    rest = body
    if body.startswith("# "):
        first_nl = body.find("\n")
        title = body[:first_nl].strip() if first_nl > 0 else body.strip()
        rest = body[first_nl + 1 :].lstrip() if first_nl > 0 else ""

    transcript_start = -1
    for marker in SECTION_MARKERS:
        idx = rest.find(marker)
        if idx >= 0 and (transcript_start < 0 or idx < transcript_start):
            transcript_start = idx
    if transcript_start < 0:
        return title, "", rest
    prefix = rest[:transcript_start].strip()
    transcript_block = rest[transcript_start:].strip()
    lines = transcript_block.split("\n", 1)
    header = lines[0]
    raw_transcript = lines[1] if len(lines) > 1 else ""
    cleaned = strip_subtitle_markup(raw_transcript)
    if not cleaned:
        return title, prefix, ""
    new_section = f"{header}\n\n{cleaned}"
    return title, prefix, new_section


def clean_body(body: str) -> str | None:
    if not VTT_GARBAGE.search(body):
        return None
    title, prefix, section = _extract_title_and_sections(body)
    if not section:
        return None
    parts = [p for p in [title, prefix, section] if p]
    return "\n\n".join(parts).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="In-place clean YouTube VTT bodies")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    storage = get_storage()
    rows = storage._connect().execute(
        "SELECT id, raw_title, body_text, extract_status, extract_error, source_meta "
        "FROM raw_items WHERE platform = 'youtube'"
    ).fetchall()
    updated = 0
    for row in rows:
        body = row["body_text"] or ""
        cleaned = clean_body(body)
        if not cleaned:
            continue
        raw_id = int(row["id"])
        if args.dry_run:
            log.info("would clean raw_id=%s len %s -> %s", raw_id, len(body), len(cleaned))
            updated += 1
            continue
        storage.update_raw_item_content(
            raw_id,
            body_text=cleaned,
            raw_title=row["raw_title"],
            extract_status=row["extract_status"],
            extract_error=row["extract_error"],
            source_meta=storage.loads_meta(row["source_meta"]) if hasattr(storage, "loads_meta") else row["source_meta"],
        )
        updated += 1
    storage.close()
    log.info("Done cleaned=%s dry_run=%s", updated, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
