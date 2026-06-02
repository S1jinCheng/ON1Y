#!/usr/bin/env python3
"""Re-fetch Zhihu author meta from API and fix wrong nav-bar avatars in source_meta."""

from __future__ import annotations

import argparse
import json
import logging

from on1y.adapters.sqlite_storage import get_storage
from on1y.ingestion.zhihu_follow_list import fetch_zhihu_me
from on1y.utils.author_meta import resolve_author_avatar
from on1y.utils.platform import PLATFORM_ZHIHU
from on1y.utils.zhihu_author import author_meta_from_user, fetch_author_meta_for_url

logger = logging.getLogger(__name__)


def _avatar_fingerprint(url: str) -> str:
    """Zhimg avatars share a stable hash segment across size/query variants."""
    import re

    value = str(url or "").strip()
    match = re.search(r"/v2-([a-f0-9]{16,})", value)
    if match:
        return match.group(1)
    return value


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max items (0=all)")
    args = parser.parse_args()

    try:
        me = fetch_zhihu_me()
        my_meta = author_meta_from_user(me)
        my_avatar = resolve_author_avatar(my_meta)
        my_fp = _avatar_fingerprint(my_avatar)
    except Exception as exc:
        logger.error("Cannot load Zhihu /me (check cookies): %s", exc)
        return 1

    storage = get_storage()
    try:
        conn = storage._connect()
        rows = conn.execute(
            """
            SELECT id, url, source_meta FROM raw_items
            WHERE platform = ? AND extract_status = 'ok'
            ORDER BY id DESC
            """,
            (PLATFORM_ZHIHU,),
        ).fetchall()
        updated = 0
        scanned = 0
        for row in rows:
            if args.limit and scanned >= args.limit:
                break
            scanned += 1
            raw_id = int(row["id"])
            url = str(row["url"])
            patch = fetch_author_meta_for_url(url)
            if not patch:
                continue
            from on1y.utils.json_util import loads_meta

            meta = loads_meta(row["source_meta"])
            old_avatar = resolve_author_avatar(meta)
            new_avatar = resolve_author_avatar(patch)
            if not new_avatar:
                continue
            if _avatar_fingerprint(old_avatar) == _avatar_fingerprint(new_avatar):
                continue
            db_author = str(meta.get("author") or "").strip()
            api_author = str(patch.get("author") or "").strip()
            wrong_nav = my_fp and _avatar_fingerprint(old_avatar) == my_fp
            same_author_mismatch = (
                api_author and db_author == api_author and _avatar_fingerprint(old_avatar) != _avatar_fingerprint(new_avatar)
            )
            if not wrong_nav and not same_author_mismatch:
                continue
            if args.dry_run:
                logger.info("would fix raw_id=%s %s -> %s", raw_id, old_avatar[:60], new_avatar[:60])
            else:
                storage.merge_source_meta(raw_id, patch)
                logger.info("fixed raw_id=%s author=%s", raw_id, patch.get("author"))
            updated += 1
        print(json.dumps({"scanned": scanned, "updated": updated, "dry_run": args.dry_run}, ensure_ascii=False))
    finally:
        storage.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
