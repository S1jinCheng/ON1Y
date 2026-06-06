"""Fetch all items from Zhihu 收藏夹 via logged-in API and enqueue for ingest."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.ingestion.enqueue import enqueue_url
from on1y.ingestion.zhihu_follow_list import (
    DEFAULT_HEADERS,
    ZHIHU_API,
    _cookie_jar,
    fetch_zhihu_favlists,
)
from on1y.ingestion.zhihu_feeds import slug_label
from on1y.models.enums import ExtractStatus, SourceType
from on1y.ports.storage import StoragePort
from on1y.utils.platform import normalize_url
from on1y.utils.zhihu_author import author_meta_from_content

logger = logging.getLogger(__name__)

SUPPORTED_CONTENT_TYPES = frozenset({"answer", "article", "zvideo"})


def normalize_zhihu_item_url(url: str) -> str:
    """Normalize Zhihu content URLs for deduplication."""
    cleaned = normalize_url(url.strip())
    parsed = urlparse(cleaned)
    if "/pin/" in parsed.path:
        return urlunparse(parsed._replace(query="", params=""))
    return cleaned


def content_to_url(content: dict[str, Any]) -> str | None:
    url = str(content.get("url") or "").strip()
    if not url:
        return None
    return normalize_zhihu_item_url(url)


def fetch_collection_items(
    collection_id: str,
    *,
    cookie_path=None,
    settings: Settings | None = None,
    page_size: int = 20,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Return collection items as {url, content_type, title, collection_id, collection_name}."""
    settings = settings or get_settings()
    path = cookie_path or settings.zhihu_cookies_path
    jar = _cookie_jar(path)
    if not jar:
        raise ConfigurationError(f"No zhihu.com cookies in {path}")

    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    rows: list[dict[str, Any]] = []
    offset = 0
    try:
        assert client is not None
        while True:
            response = client.get(
                f"{ZHIHU_API}/collections/{collection_id}/items",
                params={"offset": offset, "limit": page_size},
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("data") or []
            if not batch:
                break
            for item in batch:
                content = item.get("content") or {}
                url = content_to_url(content)
                if not url:
                    continue
                rows.append(
                    {
                        "url": url,
                        "content_type": str(content.get("type") or ""),
                        "title": _item_title(content),
                        "collection_id": collection_id,
                        "author_meta": author_meta_from_content(content),
                    }
                )
            paging = payload.get("paging") or {}
            if paging.get("is_end"):
                break
            offset += page_size
    finally:
        if own_client and client is not None:
            client.close()

    return rows


def _item_title(content: dict[str, Any]) -> str | None:
    for key in ("title", "question", "excerpt"):
        value = content.get(key)
        if isinstance(value, dict):
            value = value.get("title") or value.get("name")
        text = str(value or "").strip()
        if text:
            return text[:500]
    return None


def _should_skip_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_zhihu_item_url(url)
    raw = storage.get_raw_by_url(normalized)
    if raw is not None and raw.extract_status in (ExtractStatus.OK, ExtractStatus.PARTIAL):
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def backfill_zhihu_collections(
    storage: StoragePort,
    *,
    collection_ids: list[str] | None = None,
    include_pins: bool = False,
    dry_run: bool = False,
    max_scan_per_collection: int = 120,
    early_stop_existing_streak: int = 20,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Enqueue all items from the user's Zhihu 收藏夹 (or selected IDs).
    Returns counts per collection and overall.
    """
    settings = settings or get_settings()
    favlists = fetch_zhihu_favlists(settings=settings)
    if collection_ids:
        wanted = {str(item) for item in collection_ids}
        favlists = [f for f in favlists if str(f["id"]) in wanted]
        if not favlists:
            raise ConfigurationError(f"No matching favlists for ids: {sorted(wanted)}")

    path = settings.zhihu_cookies_path
    jar = _cookie_jar(path)
    if not jar:
        raise ConfigurationError(f"No zhihu.com cookies in {path}")

    report: dict[str, Any] = {
        "collections": [],
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_unsupported": 0,
        "unique_urls": 0,
    }
    seen_urls: set[str] = set()

    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        for fav in favlists:
            collection_id = str(fav["id"])
            collection_name = str(fav.get("name") or collection_id)
            feed_label = slug_label("collection", collection_id)
            items = fetch_collection_items(collection_id, settings=settings, client=client)
            coll_stats = {
                "id": collection_id,
                "name": collection_name,
                "total": len(items),
                "enqueued": 0,
                "skipped_existing": 0,
                "skipped_unsupported": 0,
                "skipped_duplicate": 0,
                "stopped_early": False,
            }
            existing_streak = 0
            scanned = 0
            for item in items:
                scanned += 1
                if scanned > max_scan_per_collection:
                    coll_stats["stopped_early"] = True
                    break
                content_type = item["content_type"]
                url = item["url"]
                if content_type not in SUPPORTED_CONTENT_TYPES and not (
                    include_pins and content_type == "pin"
                ):
                    coll_stats["skipped_unsupported"] += 1
                    report["skipped_unsupported"] += 1
                    continue
                if url in seen_urls:
                    coll_stats["skipped_duplicate"] += 1
                    continue
                seen_urls.add(url)
                if _should_skip_url(storage, url):
                    coll_stats["skipped_existing"] += 1
                    report["skipped_existing"] += 1
                    existing_streak += 1
                    if existing_streak >= early_stop_existing_streak:
                        coll_stats["stopped_early"] = True
                        break
                    continue
                existing_streak = 0
                if dry_run:
                    coll_stats["enqueued"] += 1
                    report["enqueued"] += 1
                    continue
                meta = {
                    "feed_label": feed_label,
                    "collection_id": collection_id,
                    "collection_name": collection_name,
                    "content_type": content_type,
                    "entry_title": item.get("title"),
                    "backfill": True,
                    "source": "zhihu_collection_api",
                }
                meta.update(item.get("author_meta") or {})
                enqueue_url(storage, url, source=SourceType.RSS, source_meta=meta)
                coll_stats["enqueued"] += 1
                report["enqueued"] += 1

            logger.info(
                "Collection %s (%s): total=%s enqueued=%s skipped=%s unsupported=%s",
                collection_name,
                collection_id,
                coll_stats["total"],
                coll_stats["enqueued"],
                coll_stats["skipped_existing"],
                coll_stats["skipped_unsupported"],
            )
            report["collections"].append(coll_stats)

    report["unique_urls"] = len(seen_urls)
    report["queue_pending"] = storage.count_pending_for_platform("zhihu") if hasattr(
        storage, "count_pending_for_platform"
    ) else None
    return report
