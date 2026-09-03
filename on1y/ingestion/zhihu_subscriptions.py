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
MOMENTS_CURSOR_KEY = "zhihu-moments://feed"
ZHIHU_MOMENTS_API = "https://www.zhihu.com/api/v3/moments"
MOMENTS_HEADERS = {
    **DEFAULT_HEADERS,
    "x-api-version": "3.0.91",
}
SUPPORTED_TARGET_TYPES = frozenset({"answer", "article", "zvideo"})
# Only original posts from followees — skip votes/likes/pins in the following feed.
MOMENT_CREATE_VERBS = frozenset(
    {
        "MEMBER_ANSWER_QUESTION",
        "MEMBER_CREATE_ARTICLE",
        "MEMBER_CREATE_ZVIDEO",
    }
)


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


def following_moments_cursor_key() -> str:
    """Global cursor for Zhihu following feed (/api/v3/moments)."""
    return MOMENTS_CURSOR_KEY


def _target_url(target: dict[str, Any]) -> str | None:
    url = str(target.get("url") or "").strip()
    if url and "api.zhihu.com" not in url:
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


def _target_social_stats(target: dict[str, Any]) -> dict[str, int]:
    """Pick engagement counters when Zhihu includes them in a target payload."""
    stats = target.get("stats") if isinstance(target.get("stats"), dict) else {}

    def first_int(*values: Any) -> int | None:
        for value in values:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                return parsed
        return None

    result: dict[str, int] = {}
    likes = first_int(
        target.get("voteup_count"),
        target.get("like_count"),
        target.get("likes"),
        stats.get("voteup_count"),
        stats.get("like_count"),
    )
    comments = first_int(
        target.get("comment_count"),
        target.get("comments"),
        stats.get("comment_count"),
        stats.get("comments"),
    )
    if likes is not None:
        result["like_count"] = likes
    if comments is not None:
        result["comment_count"] = comments
    return result


def iter_following_moments(
    client: httpx.Client,
    *,
    max_pages: int = 2,
    page_size: int = 20,
) -> Iterator[dict[str, Any]]:
    """Iterate the logged-in user's following feed (知乎「关注」时间线)."""
    url: str | None = ZHIHU_MOMENTS_API
    params: dict[str, Any] | None = {"limit": page_size}
    pages = 0
    while url and pages < max_pages:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("data") or []
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                yield item
        pages += 1
        paging = payload.get("paging") or {}
        if paging.get("is_end"):
            break
        next_url = paging.get("next")
        if not next_url:
            break
        url = str(next_url)
        params = None


def _moment_author_name(moment: dict[str, Any]) -> str:
    actors = moment.get("actors")
    if isinstance(actors, list):
        for actor in actors:
            if isinstance(actor, dict):
                name = str(actor.get("name") or "").strip()
                if name:
                    return name
    target = moment.get("target")
    if isinstance(target, dict):
        author = target.get("author")
        if isinstance(author, dict):
            name = str(author.get("name") or "").strip()
            if name:
                return name
    return "Zhihu"


def poll_zhihu_following_moments(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    backfill: bool = False,
    sync_since_ts: int | None = None,
    max_pages: int | None = None,
    backfill_max_days: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Enqueue new content from Zhihu following feed (/api/v3/moments)."""
    if user_id is None:
        from on1y.auth.context import get_effective_user_id
        user_id = get_effective_user_id()
    settings = settings or get_settings()
    from on1y.subscriptions.settings import resolve_sync_since_ts

    sync_since_ts = resolve_sync_since_ts(
        "zhihu",
        sync_since_ts=sync_since_ts,
        backfill=backfill,
        backfill_max_days=backfill_max_days,
    )

    path = resolve_cookie_path("zhihu", settings, user_id=user_id)
    jar = _cookie_jar(path)
    if not jar:
        raise ConfigurationError(f"No zhihu.com cookies in {path}")

    cursor_key = following_moments_cursor_key()
    last_id, _ = storage.get_rss_feed_state(cursor_key)
    first_run = last_id is None

    pages_max = settings.zhihu_api_poll_max_pages
    if backfill or (sync_since_ts is not None and first_run):
        pages_max = settings.zhihu_api_poll_backfill_pages
    if max_pages is not None:
        pages_max = max_pages

    report: dict[str, Any] = {
        "platform": "zhihu",
        "mode": "moments",
        "source": "following_feed",
        "pages_max": pages_max,
        "moments_seen": 0,
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_before_since": 0,
        "skipped_unsupported": 0,
        "caught_up": False,
        "sync_since_ts": sync_since_ts,
        "errors": [],
    }

    newest_id = last_id
    feed_head_id: str | None = None
    from on1y.sync.progress import get_cold_start_progress

    progress = get_cold_start_progress()

    with httpx.Client(
        headers=MOMENTS_HEADERS,
        cookies=jar,
        timeout=settings.http_timeout_seconds,
    ) as client:
        try:
            for moment in iter_following_moments(client, max_pages=pages_max):
                report["moments_seen"] += 1
                moment_id = str(moment.get("id") or "")
                if moment_id and feed_head_id is None:
                    feed_head_id = moment_id
                if (
                    not backfill
                    and not first_run
                    and last_id
                    and moment_id
                    and moment_id == last_id
                ):
                    report["caught_up"] = True
                    break

                verb = str(moment.get("verb") or "").strip()
                if verb not in MOMENT_CREATE_VERBS:
                    report["skipped_unsupported"] += 1
                    continue

                target = moment.get("target")
                if not isinstance(target, dict):
                    report["skipped_unsupported"] += 1
                    continue
                target_type = str(target.get("type") or "").strip().lower()
                if target_type not in SUPPORTED_TARGET_TYPES:
                    report["skipped_unsupported"] += 1
                    continue

                created_ts = _activity_created_ts(moment)
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

                author_name = _moment_author_name(moment)
                token = ""
                author = target.get("author")
                if isinstance(author, dict):
                    token = str(author.get("url_token") or "").strip()
                label = slug_label("activities", token or author_name)
                title = _target_title(target)
                meta = {
                    "platform": "zhihu",
                    "feed_label": label,
                    "entry_title": title,
                    "published": created_ts,
                    "entry_published": _activity_created_iso(created_ts),
                    "subscription_source": "zhihu_moments",
                    "author_name": author_name,
                }
                meta.update(_target_social_stats(target))
                enqueue_url(
                    storage,
                    url,
                    source=SourceType.RSS,
                    source_meta=meta,
                )
                report["enqueued"] += 1
                progress and progress.log_item(
                    phase="subscriptions",
                    title=title,
                    platform="zhihu",
                    status="enqueued",
                    url=url,
                    detail=author_name,
                )

        except Exception as exc:
            logger.warning("Zhihu moments poll failed: %s", exc)
            report["errors"].append({"error": str(exc)})

    if feed_head_id:
        newest_id = feed_head_id
    if newest_id and newest_id != last_id:
        storage.set_rss_feed_state(
            cursor_key,
            last_entry_id=newest_id,
            last_published=None,
        )
    return report


def poll_zhihu_api_subscriptions(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    backfill: bool = False,
    sync_since_ts: int | None = None,
    max_followees_per_run: int | None = None,
    max_pages_per_followee: int | None = None,
    backfill_max_days: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Dispatch Zhihu API poll: moments feed (default) or legacy per-followee activities."""
    if user_id is None:
        from on1y.auth.context import get_effective_user_id
        user_id = get_effective_user_id()
    settings = settings or get_settings()
    mode = str(settings.zhihu_api_poll_mode or "moments").strip().lower()
    if mode == "activities":
        return poll_zhihu_follow_activities(
            storage,
            settings=settings,
            backfill=backfill,
            sync_since_ts=sync_since_ts,
            max_followees_per_run=max_followees_per_run,
            max_pages_per_followee=max_pages_per_followee,
            backfill_max_days=backfill_max_days,
            user_id=user_id,
        )
    return poll_zhihu_following_moments(
        storage,
        settings=settings,
        backfill=backfill,
        sync_since_ts=sync_since_ts,
        backfill_max_days=backfill_max_days,
        user_id=user_id,
    )


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
    backfill_max_days: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Enqueue new content from followed Zhihu users via API (cookie only)."""
    if user_id is None:
        from on1y.auth.context import get_effective_user_id
        user_id = get_effective_user_id()
    settings = settings or get_settings()
    from on1y.subscriptions.settings import resolve_sync_since_ts

    sync_since_ts = resolve_sync_since_ts(
        "zhihu",
        sync_since_ts=sync_since_ts,
        backfill=backfill,
        backfill_max_days=backfill_max_days,
    )

    path = resolve_cookie_path("zhihu", settings, user_id=user_id)
    jar = _cookie_jar(path)
    if not jar:
        raise ConfigurationError(f"No zhihu.com cookies in {path}")

    max_followees = max_followees_per_run or settings.zhihu_api_poll_max_followees
    max_pages = max_pages_per_followee or (
        settings.zhihu_api_poll_backfill_pages
        if backfill
        else settings.zhihu_api_poll_max_pages
    )

    followees = fetch_zhihu_followees(settings=settings, user_id=user_id)
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
                    meta = {
                        "platform": "zhihu",
                        "feed_label": label,
                        "entry_title": title,
                        "published": created_ts,
                        "entry_published": _activity_created_iso(created_ts),
                        "subscription_source": "zhihu_api",
                        "author_name": name,
                    }
                    meta.update(_target_social_stats(target))
                    enqueue_url(
                        storage,
                        url,
                        source=SourceType.RSS,
                        source_meta=meta,
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

    storage.set_rss_feed_state(
        f"{CURSOR_KEY}-rotate",
        last_entry_id=str(next_rotate),
        last_published=None,
    )
    return report
