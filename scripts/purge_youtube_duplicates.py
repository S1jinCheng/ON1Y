"""Remove YouTube raw_items that duplicate an existing Bilibili video (same title)."""
from __future__ import annotations

import argparse
import logging

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import user_context
from on1y.utils.video_dedup import purge_youtube_duplicates_of_bilibili

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge YouTube duplicates of Bilibili videos")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    storage = get_storage()
    try:
        with user_context(args.user_id):
            stats = purge_youtube_duplicates_of_bilibili(storage, dry_run=args.dry_run)
    finally:
        storage.close()
    logger.info("Purge complete: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
