#!/usr/bin/env python3
"""Backfill Zhihu author name / avatar into source_meta via API."""

from __future__ import annotations

import argparse
import json
import logging
import sys

import httpx

from on1y.adapters.sqlite_storage import get_storage
from on1y.config import get_settings
from on1y.ingestion.zhihu_collections import normalize_zhihu_item_url
from on1y.ingestion.zhihu_follow_list import DEFAULT_HEADERS, ZHIHU_API, _cookie_jar, fetch_zhihu_favlists
from on1y.utils.author_meta import resolve_author_avatar
from on1y.utils.zhihu_author import author_meta_from_content, fetch_author_meta_for_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backfill_zhihu_author")


def _needs_author(meta: dict) -> bool:
    name = str(meta.get("author") or "").strip()
    avatar = resolve_author_avatar(meta)
    return not name or not avatar


def _collection_author_map(client: httpx.Client) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for fav in fetch_zhihu_favlists():
        offset = 0
        while True:
            response = client.get(
                f"{ZHIHU_API}/collections/{fav['id']}/items",
                params={"offset": offset, "limit": 20},
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("data") or []
            if not batch:
                break
            for row in batch:
                content = row.get("content") or {}
                url = content.get("url")
                if not url:
                    continue
                meta = author_meta_from_content(content)
                if meta:
                    mapping[normalize_zhihu_item_url(str(url))] = meta
            if (payload.get("paging") or {}).get("is_end"):
                break
            offset += 20
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Zhihu author metadata")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    settings = get_settings()
    jar = _cookie_jar(settings.zhihu_cookies_path)
    storage = get_storage()
    conn = storage._connect()

    updated = 0
    scanned = 0
    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        url_author = _collection_author_map(client)
        log.info("Loaded author hints for %s collection URLs", len(url_author))

        rows = conn.execute(
            "SELECT id, url, source_meta FROM raw_items WHERE platform = 'zhihu' ORDER BY id"
        ).fetchall()
        for row in rows:
            if args.limit and scanned >= args.limit:
                break
            scanned += 1
            raw_id = int(row["id"])
            url = str(row["url"])
            meta = json.loads(row["source_meta"] or "{}")
            if not _needs_author(meta):
                continue
            patch = url_author.get(normalize_zhihu_item_url(url)) or fetch_author_meta_for_url(
                url, client=client
            )
            if not patch:
                continue
            if args.dry_run:
                log.info("would update raw_id=%s author=%s", raw_id, patch.get("author"))
                updated += 1
                continue
            storage.merge_source_meta(raw_id, patch)
            updated += 1
            if updated % 25 == 0:
                log.info("updated %s items...", updated)

    storage.close()
    log.info("Done updated=%s scanned=%s dry_run=%s", updated, scanned, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
