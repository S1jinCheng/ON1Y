#!/usr/bin/env python3
"""Sync followed Bilibili UPs into feeds.yaml and enqueue new uploads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Bilibili UP subscriptions")
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="Only refresh feeds.yaml from follow list",
    )
    parser.add_argument(
        "--poll-only",
        action="store_true",
        help="Only poll for new videos (respects ON1Y_BILIBILI_UP_POLL_MODE)",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Enqueue recent uploads per UP (respects ON1Y_RSS_BACKFILL_MAX_ITEMS_PER_FEED)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print feeds.yaml only")
    parser.add_argument("--disabled", action="store_true", help="Write feeds as enabled: false")
    args = parser.parse_args()

    from on1y.adapters.sqlite_storage import get_storage
    from on1y.config import get_settings
    from on1y.ingestion.bilibili_subscriptions import sync_bilibili_up_config
    from on1y.subscriptions import sync_subscriptions

    settings = get_settings()
    sync_config = not args.poll_only
    poll = not args.config_only and not args.dry_run

    if args.dry_run:
        from on1y.ingestion.bilibili_api import fetch_bilibili_followings
        from on1y.ingestion.bilibili_feeds import merge_bilibili_up_feeds_yaml

        followings = fetch_bilibili_followings(settings=settings)
        merge_bilibili_up_feeds_yaml(
            followings,
            feeds_path=settings.rss_config_path,
            rsshub_base=settings.bilibili_rsshub_base,
            enabled=not args.disabled,
            dry_run=True,
        )
        print(json.dumps({"followings_fetched": len(followings)}, ensure_ascii=False, indent=2))
        return 0

    storage = get_storage()
    try:
        if args.config_only:
            report = sync_bilibili_up_config(settings=settings, enabled=not args.disabled)
        else:
            report = sync_subscriptions(
                storage,
                platform="bilibili",
                sync_config=sync_config,
                poll=poll,
                backfill=args.backfill,
            )
            if isinstance(report, dict) and "bilibili" in report:
                report = report["bilibili"]
    finally:
        storage.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Next: on1y worker --once  # or on1y catchup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
