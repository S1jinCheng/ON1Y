"""Poll Zhihu followees via logged-in API (no RSSHub required)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx

from on1y.config import Settings, get_settings
from on1y.cookies.loader import resolve_cookie_path
from on1y.exceptions import ConfigurationError
from on1y.ingestion.enqueue import enqueue_url
from on1y.ingestion.zhihu_feeds import slug_label
from on1y.ingestion.zhihu_collections import normalize_zhihu_item_url
from on1y.ingestion.zhihu_follow_list import (
    DEFAULT_HEADERS,
    ZHIHU_API,
    _cookie_jar,
    fetch_zhihu_followees,
)
from on1y.models.enums import SourceType
from on1y.ports.storage import StoragePort

logger = logging.getLogger(__name__)

CURSOR_KEY = "zhihu-api-follow"
SUPPORTED_TARGET_TYPES = frozenset({"answer", "article", "zvideo"})


def _should_skip_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_zhihu_item_url(url)
    if storage.get_raw_by_url(normalized) is not None:
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def _activity_created_ts(item: dict[str, Any]) -> int | None:
    for key in ("created_time", "updated_time"):
        raw = item.get(key)
        if isinstance(raw, (int, float)) and raw > 0:
            return int(raw)
    return None


def _activity_created_iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _target_url(target: dict[str, Any]) -> str | None:
    url = str(target.get("url") or "").strip()
    if url:
        return url
    target_type = str(target.get("type") or "").strip().lower()
    target_id = target.get("id")
    if target_type == "answer" and target_id is not None:
        question = target.get("question") if isinstance(target.get("question"), dict) else {}
        qid = question.get("id")
        if qid is not None:
            return f"https://www.zhihu.com/question/{qid}/answer/{target_id}"
    if target_type == "article" and target_id is not None:
        return f"https://zhuanlan.zhihu.com/p/{target_id}"
    if target_type == "zvideo" and target_id is not None:
        return f"https://www.zhihu.com/zvideo/{target_id}"
    return None


def _target_title(target: dict[str, Any]) -> str:
    target_type = str(target.get("type") or "").strip().lower()
    if target_type == "answer":
        question = target.get("question") if isinstance(target.get("question"), dict) else {}
        title = str(question.get("title") or "").strip()
        if title:
            return title
    for key in ("title", "excerpt", "content"):
        text = str(target.get(key) or "").strip()
        if text:
            return text[:200]
    return str(target.get("url") or "Zhihu item")


def iter_member_activities(
    client: httpx.Client,
    *,
    url_token: str,
    max_pages: int = 2,
    page_size: int = 20,
) -> Iterator[dict[str, Any]]:
    offset = 0
    for _ in range(max_pages):
        response = client.get(
            f"{ZHIHU_API}/members/{url_token}/activities",
            params={
                "offset": offset,
                "limit": page_size,
                "include": "data[*].target",
            },
        )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("data") or []
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                yield item
        paging = payload.get("paging") or {}
        if paging.get("is_end"):
            break
        offset += page_size


def poll_zhihu_follow_activities(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    backfill: bool = False,
    sync_since_ts: int | None = None,
    max_followees_per_run: int | None = None,
    max_pages_per_followee: int | None = None,
) -> dict[str, Any]:
    """Enqueue new content from followed Zhihu users via API (cookie only)."""
    settings = settings or get_settings()
    if sync_since_ts is None:
        from on1y.subscriptions.settings import sync_since_timestamp

        sync_since_ts = sync_since_timestamp("zhihu")

    path = resolve_cookie_path("zhihu", settings)
    jar = _cookie_jar(path)
    if not jar:
        raise ConfigurationError(f"No zhihu.com cookies in {path}")

    max_followees = max_followees_per_run or settings.zhihu_api_poll_max_followees
    max_pages = max_pages_per_followee or (
        settings.zhihu_api_poll_backfill_pages
        if backfill
        else settings.zhihu_api_poll_max_pages
    )

    followees = fetch_zhihu_followees(settings=settings)
    rotate_raw, _ = storage.get_rss_feed_state(f"{CURSOR_KEY}-rotate")
    rotate = int(rotate_raw) if rotate_raw and str(rotate_raw).isdigit() else 0
    if not followees:
        return {
            "platform": "zhihu",
            "mode": "api",
            "followees": 0,
            "enqueued": 0,
            "skipped_existing": 0,
            "skipped_before_since": 0,
            "errors": [],
        }

    slice_end = rotate + max_followees
    batch = followees[rotate:slice_end]
    if len(batch) < max_followees:
        batch = batch + followees[: max(0, max_followees - len(batch))]
    next_rotate = (rotate + max_followees) % len(followees)

    report: dict[str, Any] = {
        "platform": "zhihu",
        "mode": "api",
        "followees_total": len(followees),
        "followees_polled": len(batch),
        "rotate_next": next_rotate,
        "pages_per_followee": max_pages,
        "activities_seen": 0,
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_before_since": 0,
        "skipped_unsupported": 0,
        "sync_since_ts": sync_since_ts,
        "errors": [],
    }

    from on1y.sync.progress import get_cold_start_progress

    progress = get_cold_start_progress()

    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        for followee in batch:
            token = str(followee.get("url_token") or "").strip()
            name = str(followee.get("name") or token)
            if not token:
                continue
            label = slug_label("activities", token)
            try:
                for activity in iter_member_activities(
                    client, url_token=token, max_pages=max_pages
                ):
                    report["activities_seen"] += 1
                    target = activity.get("target")
                    if not isinstance(target, dict):
                        report["skipped_unsupported"] += 1
                        continue
                    target_type = str(target.get("type") or "").strip().lower()
                    if target_type not in SUPPORTED_TARGET_TYPES:
                        report["skipped_unsupported"] += 1
                        continue
                    created_ts = _activity_created_ts(activity)
                    if (
                        sync_since_ts is not None
                        and created_ts is not None
                        and created_ts < sync_since_ts
                    ):
                        report["skipped_before_since"] += 1
                        continue
                    url = _target_url(target)
                    if not url:
                        report["skipped_unsupported"] += 1
                        continue
                    if _should_skip_url(storage, url):
                        report["skipped_existing"] += 1
                        continue
                    title = _target_title(target)
                    enqueue_url(
                        storage,
                        url,
                        source=SourceType.RSS,
                        source_meta={
                            "platform": "zhihu",
                            "feed_label": label,
                            "entry_title": title,
                            "published": created_ts,
                            "entry_published": _activity_created_iso(created_ts),
                            "subscription_source": "zhihu_api",
                            "author_name": name,
                        },
                    )
                    report["enqueued"] += 1
                    progress and progress.log_item(
                        phase="subscriptions",
                        title=title,
                        platform="zhihu",
                        status="enqueued",
                        url=url,
                        detail=name,
                    )
            except Exception as exc:
                logger.warning("Zhihu API poll for %s failed: %s", token, exc)
                report["errors"].append({"url_token": token, "error": str(exc)})

    storage.set_rss_feed_state(f"{CURSOR_KEY}-rotate", str(next_rotate), None)
    return report
