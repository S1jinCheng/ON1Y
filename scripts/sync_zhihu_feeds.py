#!/usr/bin/env python3
"""
Generate Zhihu RSSHub entries in config/feeds.yaml from config/zhihu_follows.txt.

See docs/ZHIHU_PIPELINE.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOLLOWS_FILE = PROJECT_ROOT / "config" / "zhihu_follows.txt"
DEFAULT_FEEDS_PATH = PROJECT_ROOT / "config" / "feeds.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Zhihu follows into feeds.yaml (RSSHub)")
    parser.add_argument(
        "--from-file",
        type=Path,
        default=DEFAULT_FOLLOWS_FILE,
        help=f"Follows list (default: {DEFAULT_FOLLOWS_FILE})",
    )
    parser.add_argument("--feeds", type=Path, default=DEFAULT_FEEDS_PATH)
    parser.add_argument(
        "--rsshub-base",
        default=None,
        help="RSSHub base URL (default: ON1Y_ZHIHU_RSSHUB_BASE or http://127.0.0.1:1200)",
    )
    parser.add_argument(
        "--from-follow-list",
        action="store_true",
        help="Fetch logged-in Zhihu follow list via API and merge into follows file",
    )
    parser.add_argument(
        "--from-favlists",
        action="store_true",
        help="Fetch logged-in Zhihu 收藏夹 via API and merge into follows file",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--disabled", action="store_true", help="Add feeds as enabled: false")
    args = parser.parse_args()

    from on1y.config import get_settings
    from on1y.ingestion.zhihu_feeds import follows_from_file, merge_zhihu_feeds_yaml

    settings = get_settings()
    rsshub_base = (args.rsshub_base or settings.zhihu_rsshub_base).strip()
    if not rsshub_base.startswith("http"):
        print("Invalid RSSHub base URL.", file=sys.stderr)
        return 1

    follows = follows_from_file(args.from_file) if args.from_file.is_file() else []

    if args.from_follow_list:
        from on1y.ingestion.zhihu_follow_list import fetch_zhihu_followees, merge_follows_file

        followees = fetch_zhihu_followees(settings=settings)
        if args.dry_run:
            print(f"Would sync {len(followees)} followee(s) into {args.from_file}")
            for user in followees[:5]:
                print(f"  {user['feed_type']}:{user['url_token']}  ({user['name']})")
            if len(followees) > 5:
                print(f"  ... and {len(followees) - 5} more")
            follows.extend(
                (user.get("feed_type", "activities"), user["url_token"]) for user in followees
            )
        else:
            added, total = merge_follows_file(followees, args.from_file)
            print(
                f"Synced {len(followees)} followee(s); added {added}, total {total} in {args.from_file}"
            )
            follows = follows_from_file(args.from_file)

    if args.from_favlists:
        from on1y.ingestion.zhihu_follow_list import fetch_zhihu_favlists, merge_follows_file

        favlists = fetch_zhihu_favlists(settings=settings)
        if args.dry_run:
            print(f"Would sync {len(favlists)} favlist(s) into {args.from_file}")
            for fav in favlists:
                print(f"  collection:{fav['id']}  ({fav['name']})")
            follows.extend(("collection", fav["id"]) for fav in favlists)
        else:
            added, total = merge_follows_file(favlists, args.from_file)
            print(
                f"Synced {len(favlists)} favlist(s); added {added}, total {total} in {args.from_file}"
            )
            follows = follows_from_file(args.from_file)

    if not args.from_file.is_file() and not follows:
        print(
            f"Follows file not found: {args.from_file}\n"
            f"Create it from config/zhihu_follows.txt.example",
            file=sys.stderr,
        )
        return 1

    if not args.from_file.is_file() and follows and not args.dry_run:
        args.from_file.parent.mkdir(parents=True, exist_ok=True)
        args.from_file.write_text("", encoding="utf-8")

    if not follows and args.from_file.is_file():
        follows = follows_from_file(args.from_file)

    if not follows:
        print(f"No follows parsed from {args.from_file}", file=sys.stderr)
        return 1

    count = merge_zhihu_feeds_yaml(
        follows,
        feeds_path=args.feeds,
        rsshub_base=rsshub_base,
        enabled=not args.disabled,
        dry_run=args.dry_run,
    )
    print(f"{'Would add' if args.dry_run else 'Added'} {count} Zhihu feed(s) to {args.feeds}")
    print("Next:")
    print("  python scripts/import_cookies.py zhihu ~/Downloads/zhihu-cookies.json")
    print("  on1y rss poll")
    print("  on1y pipeline zhihu --ingest 3 --distill 5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
