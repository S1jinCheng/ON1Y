#!/usr/bin/env python3
"""Enqueue all videos from logged-in Bilibili 收藏夹 via API."""

from __future__ import annotations

import argparse
import logging
import sys

from on1y.adapters.sqlite_storage import get_storage
from on1y.ingestion.bilibili_collections import backfill_bilibili_collections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backfill_bilibili_collections")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Bilibili favlists into pending_urls")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--folder-id", action="append", dest="folder_ids")
    parser.add_argument(
        "--ingest",
        type=int,
        default=0,
        help="After enqueue, run video worker with this batch size (0=skip)",
    )
    args = parser.parse_args()

    storage = get_storage()
    try:
        report = backfill_bilibili_collections(
            storage,
            folder_ids=args.folder_ids,
            dry_run=args.dry_run,
        )
    finally:
        storage.close()

    log.info(
        "Done enqueued=%s skipped_existing=%s duplicate=%s duplicate_deleted=%s unique=%s queue_pending=%s dry_run=%s",
        report["enqueued"],
        report["skipped_existing"],
        report["skipped_duplicate"],
        report["skipped_duplicate_deleted"],
        report["unique_urls"],
        report.get("queue_pending"),
        args.dry_run,
    )
    for folder in report["folders"]:
        log.info(
            "  [%s] %s: total=%s +enqueue=%s skip=%s dup=%s dup_deleted=%s",
            folder["id"],
            folder["name"],
            folder["total"],
            folder["enqueued"],
            folder["skipped_existing"],
            folder["skipped_duplicate"],
            folder["skipped_duplicate_deleted"],
        )

    if args.dry_run or args.ingest <= 0:
        return 0

    from on1y.adapters.sqlite_storage import get_storage as gs
    from on1y.pipeline.worker import run_worker_batch

    storage = gs()
    try:
        result = run_worker_batch(storage, args.ingest, close_storage=True)
        log.info("Ingest batch: %s", result)
    finally:
        if storage is not None:
            try:
                storage.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
