#!/usr/bin/env python3
"""Enqueue all items from logged-in Zhihu 收藏夹 via API (full backfill)."""

from __future__ import annotations

import argparse
import logging
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.ingestion.zhihu_collections import backfill_zhihu_collections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backfill_zhihu_collections")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Zhihu favlists into pending_urls")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--collection-id", action="append", dest="collection_ids")
    parser.add_argument("--include-pins", action="store_true", help="Also enqueue 想法 (pin) URLs")
    parser.add_argument(
        "--ingest",
        type=int,
        default=0,
        help="After enqueue, run zhihu catchup with this many items per round (0=skip)",
    )
    parser.add_argument("--max-rounds", type=int, default=500)
    args = parser.parse_args()

    storage = get_storage()
    try:
        report = backfill_zhihu_collections(
            storage,
            collection_ids=args.collection_ids,
            include_pins=args.include_pins,
            dry_run=args.dry_run,
        )
    finally:
        storage.close()

    log.info(
        "Done enqueued=%s skipped_existing=%s unsupported=%s unique_urls=%s queue_pending=%s dry_run=%s",
        report["enqueued"],
        report["skipped_existing"],
        report["skipped_unsupported"],
        report["unique_urls"],
        report.get("queue_pending"),
        args.dry_run,
    )
    for coll in report["collections"]:
        log.info(
            "  [%s] %s: total=%s +enqueue=%s skip=%s unsupported=%s dup=%s",
            coll["id"],
            coll["name"],
            coll["total"],
            coll["enqueued"],
            coll["skipped_existing"],
            coll["skipped_unsupported"],
            coll["skipped_duplicate"],
        )

    if args.dry_run or args.ingest <= 0:
        return 0

    from on1y.adapters.sqlite_storage import get_storage as gs
    from on1y.pipeline.zhihu_catchup import run_zhihu_catchup

    storage = gs()
    try:
        catchup = run_zhihu_catchup(
            storage,
            ingest_per_round=args.ingest,
            max_rounds=args.max_rounds,
        )
        log.info("Catchup: %s", catchup)
    finally:
        storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
