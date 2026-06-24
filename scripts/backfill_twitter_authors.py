"""Backfill X/Twitter author_url in source_meta from stored Markdown bodies."""
from __future__ import annotations

import argparse
import logging

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import user_context
from on1y.extract.twitter_body import parse_twitter_author_from_markdown
from on1y.knowledge.creators import normalize_twitter_author_url
from on1y.utils.author_meta import merge_author_meta
from on1y.utils.json_util import dumps_meta, loads_meta

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backfill(*, user_id: int) -> dict[str, int]:
    storage = get_storage()
    stats = {"updated": 0, "skipped": 0}
    try:
        with user_context(user_id):
            conn = storage._connect()
            user_clause, user_params = storage._user_scope_parts(conn)
            user_filter = f" AND {user_clause}" if user_clause else ""
            rows = conn.execute(
                f"""
                SELECT r.id, r.body_text, r.source_meta
                FROM raw_items r
                WHERE r.platform = 'twitter'
                  AND r.deleted_at IS NULL
                  {user_filter}
                ORDER BY r.id ASC
                """,
                user_params,
            ).fetchall()
            for row in rows:
                raw_id = int(row["id"])
                meta = loads_meta(row["source_meta"])
                if normalize_twitter_author_url(str(meta.get("author_url") or "")):
                    stats["skipped"] += 1
                    continue
                parsed = parse_twitter_author_from_markdown(str(row["body_text"] or ""))
                handle = str(parsed.get("handle") or "").strip()
                author = str(parsed.get("author") or "").strip()
                if not handle and not author:
                    stats["skipped"] += 1
                    continue
                author_url = normalize_twitter_author_url(
                    f"https://x.com/{handle}" if handle else ""
                )
                patch = merge_author_meta(
                    {},
                    {
                        "author": author,
                        "author_url": author_url,
                    },
                )
                if not patch:
                    stats["skipped"] += 1
                    continue
                new_meta = merge_author_meta(meta, patch)
                conn.execute(
                    "UPDATE raw_items SET source_meta = ?, updated_at = datetime('now') WHERE id = ?",
                    (dumps_meta(new_meta), raw_id),
                )
                stats["updated"] += 1
            conn.commit()
    finally:
        storage.close()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill X author_url from Markdown bodies")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()
    stats = backfill(user_id=args.user_id)
    logger.info("Backfill done: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
