#!/usr/bin/env python3
"""Repair Zhihu raw_title from API / cleaned RSS entry_title."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3

from on1y.adapters.sqlite_storage import get_storage
from on1y.models.enums import ExtractStatus
from on1y.utils.json_util import loads_meta
from on1y.utils.zhihu_title import resolve_zhihu_title

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    storage = get_storage()
    conn = sqlite3.connect("data/on1y.db")
    rows = conn.execute(
        "SELECT id, url, raw_title, source_meta, extract_status, body_text FROM raw_items WHERE platform='zhihu'"
    ).fetchall()
    conn.close()

    updated = 0
    for row in rows:
        rid, url, raw_title, meta_raw, status, body = row
        meta = loads_meta(meta_raw)
        old = (raw_title or "").strip()
        needs_api = (
            not old
            or "<" in old
            or "发布了想法" in old
            or "赞同了想法" in old
            or old.startswith("http")
        )
        new_title = resolve_zhihu_title(url, raw_title, meta, fetch_api=needs_api)
        if new_title == old:
            continue
        if args.dry_run:
            logger.info("would fix id=%s\n  old: %r\n  new: %r", rid, old[:60], new_title[:60])
        else:
            raw = storage.get_raw_by_id(rid)
            if raw is None:
                continue
            storage.update_raw_item_content(
                rid,
                body_text=raw.body_text,
                raw_title=new_title,
                extract_status=ExtractStatus(raw.extract_status.value),
                extract_error=raw.extract_error,
                source_meta=dict(raw.source_meta or {}),
            )
            logger.info("fixed id=%s -> %s", rid, new_title[:70])
        updated += 1

    storage.close()
    print(json.dumps({"scanned": len(rows), "updated": updated, "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
