"""Sync followed Bilibili UPs into feeds.yaml and enqueue new uploads."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from on1y.config import Settings, get_settings
from on1y.user.feeds_config import resolve_feeds_config_path
from on1y.exceptions import ConfigurationError
from on1y.ingestion.bilibili_api import (
    DEFAULT_HEADERS,
    _cookie_jar,
    fetch_bilibili_followings,
    iter_dynamic_video_feed,
    iter_up_recent_videos,
)
from on1y.ingestion.bilibili_feeds import (
    BILI_UP_FEED_LABEL_PREFIX,
    dynamic_video_cursor_key,
    merge_bilibili_up_feeds_yaml,
    slug_label,
    up_cursor_key,
)
from on1y.cookies.loader import resolve_cookie_path
from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import SourceType
from on1y.ports.storage import StoragePort
from on1y.utils.author_meta import author_meta_patch
from on1y.utils.bilibili_url import bilibili_video_url, normalize_bilibili_url
from on1y.utils.platform import normalize_url
from on1y.utils.video_dedup import (
    find_youtube_duplicate,
    remove_bilibili_duplicate_of_youtube,
    youtube_title_index,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_MARKERS = ("过于频繁", "请求过于频繁", "-799")


def _is_bilibili_rate_limit(exc: BaseException) -> bool:
    text = str(exc)
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _rate_limit_wait_seconds(settings: Settings, attempt: int) -> float:
    base = settings.bilibili_up_poll_rate_limit_backoff_seconds
    cap = settings.bilibili_up_poll_rate_limit_max_backoff_seconds
    return min(base * (2**attempt), cap)


def _video_created_ts(created: Any) -> int | None:
    try:
        return int(created)
    except (TypeError, ValueError):
        return None


def _video_created_iso(created: Any) -> str | None:
    try:
        ts = int(created)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")


def _video_url(arc: dict[str, Any]) -> str | None:
    bvid = str(arc.get("bvid") or arc.get("bv_id") or "").strip()
    if not bvid:
        return None
    return normalize_bilibili_url(bilibili_video_url(bvid))


def _should_skip_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_bilibili_url(url)
    raw = storage.get_raw_by_url(normalized)
    if raw is not None:
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def _is_newer(entry_id: str, published: str | None, last_id: str | None, last_published: str | None) -> bool:
    if last_id is None:
        return True
    if published and last_published:
        from email.utils import parsedate_to_datetime

        try:
            pub_dt = parsedate_to_datetime(published)
            last_dt = parsedate_to_datetime(last_published)
            if pub_dt and last_dt:
                return pub_dt > last_dt
        except (TypeError, ValueError):
            pass
    return entry_id != last_id


def sync_bilibili_up_config(
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    enabled: bool = True,
    user_id: int | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    cookie_path = resolve_cookie_path("bilibili", settings, user_id=user_id)
    followings = fetch_bilibili_followings(settings=settings, cookie_path=cookie_path)
    count = merge_bilibili_up_feeds_yaml(
        followings,
        feeds_path=resolve_feeds_config_path(settings, user_id=user_id),
        rsshub_base=settings.bilibili_rsshub_base,
        enabled=enabled,
        dry_run=dry_run,
    )
    return {
        "platform": "bilibili",
        "followings_fetched": len(followings),
        "feeds_merged": count,
        "dry_run": dry_run,
    }


def _fetch_up_videos_with_retry(
    up_mid: str,
    *,
    settings: Settings,
    client: httpx.Client,
    since_ts: int | None = None,
    backfill: bool = False,
    since_backfill: bool = False,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    if max_pages is None:
        max_pages = settings.bilibili_up_poll_max_pages
        if backfill:
            max_pages = max(max_pages, settings.bilibili_up_poll_backfill_max_pages)
        elif since_backfill:
            max_pages = max(max_pages, settings.bilibili_up_poll_since_max_pages)
    last_exc: Exception | None = None
    retries = settings.bilibili_up_poll_rate_limit_retries
    for attempt in range(retries):
        try:
            return list(
                iter_up_recent_videos(
                    up_mid,
                    settings=settings,
                    page_size=settings.bilibili_up_poll_page_size,
                    max_pages=max_pages,
                    since_ts=since_ts,
                    client=client,
                )
            )
        except ConfigurationError as exc:
            last_exc = exc
            if not _is_bilibili_rate_limit(exc) or attempt >= retries - 1:
                raise
            wait = _rate_limit_wait_seconds(settings, attempt)
            logger.warning(
                "Bilibili rate limit for mid=%s; retry in %.0fs (attempt %s/%s)",
                up_mid,
                wait,
                attempt + 1,
                retries,
            )
            time.sleep(wait)
    if last_exc is not None:
        raise last_exc
    return []


def _sort_ups_for_poll(storage: StoragePort, ups: list[dict[str, str]]) -> list[dict[str, str]]:
    """Poll UPs without cursor first so backfill makes steady progress across runs."""

    def sort_key(row: dict[str, str]) -> tuple[int, str]:
        up_mid = str(row.get("mid") or "").strip()
        last_id, _ = storage.get_rss_feed_state(up_cursor_key(up_mid))
        return (0 if last_id is None else 1, up_mid)

    return sorted(ups, key=sort_key)


def _dynamic_to_arc(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "bvid": parsed.get("bvid"),
        "title": parsed.get("title"),
        "created": parsed.get("created"),
        "description": parsed.get("description"),
        "desc": parsed.get("description"),
        "pic": parsed.get("pic"),
        "duration": parsed.get("duration_sec"),
    }


def poll_bilibili_dynamic_updates(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    backfill: bool = False,
    sync_since_ts: int | None = None,
    max_pages: int | None = None,
    backfill_max_days: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Enqueue new videos from following dynamics (polymer feed, type=video)."""
    settings = settings or get_settings()
    from on1y.subscriptions.settings import resolve_sync_since_ts

    sync_since_ts = resolve_sync_since_ts(
        "bilibili",
        sync_since_ts=sync_since_ts,
        backfill=backfill,
        backfill_max_days=backfill_max_days,
    )

    cursor_key = dynamic_video_cursor_key()
    last_id, last_published = storage.get_rss_feed_state(cursor_key)
    first_run = last_id is None and last_published is None

    pages_max = settings.bilibili_dynamic_poll_max_pages
    if backfill or (sync_since_ts is not None and first_run):
        pages_max = settings.bilibili_dynamic_poll_backfill_max_pages
    if max_pages is not None:
        pages_max = max_pages

    path = resolve_cookie_path("bilibili", settings, user_id=user_id)
    jar = _cookie_jar(path)
    title_index = youtube_title_index(storage)

    report: dict[str, Any] = {
        "platform": "bilibili",
        "mode": "dynamic",
        "source": "following_dynamics_video",
        "pages_max": pages_max,
        "videos_seen": 0,
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_youtube_dup": 0,
        "skipped_before_since": 0,
        "caught_up": False,
        "sync_since_ts": sync_since_ts,
        "errors": [],
        "skip_stats": {},
    }

    skip_stats: dict[str, int] = {}
    use_since_in_fetch = backfill or (sync_since_ts is not None and first_run)
    newest_id = last_id
    newest_pub = last_published

    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        try:
            for parsed in iter_dynamic_video_feed(
                settings=settings,
                max_pages=pages_max,
                since_ts=sync_since_ts if use_since_in_fetch else None,
                client=client,
                skip_stats=skip_stats,
            ):
                report["videos_seen"] += 1
                dynamic_id = str(parsed.get("dynamic_id") or parsed.get("bvid") or "")
                if (
                    not backfill
                    and not first_run
                    and last_id
                    and dynamic_id == last_id
                ):
                    report["caught_up"] = True
                    break

                created_ts = _video_created_ts(parsed.get("created"))
                if (
                    sync_since_ts is not None
                    and created_ts is not None
                    and created_ts < sync_since_ts
                ):
                    report["skipped_before_since"] += 1
                    continue

                url = _video_url(_dynamic_to_arc(parsed))
                if not url:
                    continue

                up_mid = str(parsed.get("up_mid") or "")
                uname = str(parsed.get("uname") or up_mid)
                label = slug_label(up_mid, uname)
                entry_id = str(parsed.get("bvid") or url)
                published = _video_created_iso(parsed.get("created"))

                if _should_skip_url(storage, url):
                    report["skipped_existing"] += 1
                else:
                    _enqueue_bilibili_video(
                        storage,
                        url=url,
                        arc=_dynamic_to_arc(parsed),
                        up_mid=up_mid,
                        uname=uname,
                        up_face=str(parsed.get("up_face") or "").strip() or None,
                        label=label,
                        title_index=title_index,
                        report=report,
                        backfill=backfill or use_since_in_fetch,
                        subscription_source="bilibili_dynamic",
                    )

                if _is_newer(entry_id, published, newest_id, newest_pub):
                    newest_id = dynamic_id or entry_id
                    newest_pub = published
        except Exception as exc:
            logger.warning("Bilibili dynamic poll failed: %s", exc)
            report["errors"].append({"error": str(exc)})
            if _is_bilibili_rate_limit(exc):
                report["rate_limited"] = 1

    report["skip_stats"] = skip_stats
    if newest_id:
        storage.set_rss_feed_state(
            cursor_key,
            last_entry_id=newest_id,
            last_published=newest_pub,
        )

    return report


def poll_bilibili_up_updates(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    followings: list[dict[str, str]] | None = None,
    backfill: bool = False,
    max_items_per_up: int | None = None,
    max_ups_per_run: int | None = None,
    max_pages_per_up: int | None = None,
    sync_since_ts: int | None = None,
    subscription_source: str = "bilibili_up",
    backfill_max_days: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Enqueue new uploads from followed UPs via Bilibili API.
    Uses rss_feed_state keyed by bilibili-up://{mid}.
    """
    settings = settings or get_settings()
    from on1y.subscriptions.settings import resolve_sync_since_ts

    sync_since_ts = resolve_sync_since_ts(
        "bilibili",
        sync_since_ts=sync_since_ts,
        backfill=backfill,
        backfill_max_days=backfill_max_days,
    )
    ups = followings or fetch_bilibili_followings(settings=settings)
    ups = _sort_ups_for_poll(storage, ups)
    per_up_limit = max_items_per_up if max_items_per_up is not None else settings.rss_backfill_max_items_per_feed
    ups_per_run = (
        settings.bilibili_up_poll_max_ups_per_run
        if max_ups_per_run is None
        else max_ups_per_run
    )

    from on1y.cookies.loader import resolve_cookie_path

    path = resolve_cookie_path("bilibili", settings, user_id=user_id)
    jar = _cookie_jar(path)
    title_index = youtube_title_index(storage)

    report: dict[str, Any] = {
        "platform": "bilibili",
        "ups_total": len(ups),
        "ups_attempted": 0,
        "ups_polled": 0,
        "ups_deferred": 0,
        "rate_limited": 0,
        "stopped_early": False,
        "stop_reason": None,
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_youtube_dup": 0,
        "skipped_before_since": 0,
        "sync_since_ts": sync_since_ts,
        "errors": [],
    }

    cooldown_pending = 0.0
    consecutive_rate_limits = 0
    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        for index, row in enumerate(ups):
            if ups_per_run > 0 and report["ups_attempted"] >= ups_per_run:
                report["ups_deferred"] = len(ups) - index
                logger.info(
                    "Bilibili UP poll deferred %s UPs (max_ups_per_run=%s)",
                    report["ups_deferred"],
                    ups_per_run,
                )
                break

            up_mid = str(row.get("mid") or "").strip()
            uname = str(row.get("uname") or up_mid)
            if not up_mid:
                continue

            if cooldown_pending > 0:
                logger.warning(
                    "Bilibili global cooldown %.0fs before mid=%s",
                    cooldown_pending,
                    up_mid,
                )
                time.sleep(cooldown_pending)
                cooldown_pending = 0.0
            elif index > 0 and settings.bilibili_up_poll_interval_seconds > 0:
                time.sleep(settings.bilibili_up_poll_interval_seconds)

            report["ups_attempted"] += 1
            cursor_key = up_cursor_key(up_mid)
            last_id, last_published = storage.get_rss_feed_state(cursor_key)
            label = slug_label(up_mid, uname)
            first_run = last_id is None and last_published is None
            # Full backfill only when explicitly requested. sync-since uses a smaller page cap.
            effective_backfill = backfill
            since_backfill = sync_since_ts is not None and first_run and not backfill

            try:
                videos = _fetch_up_videos_with_retry(
                    up_mid,
                    settings=settings,
                    client=client,
                    since_ts=sync_since_ts if (effective_backfill or since_backfill) else None,
                    backfill=effective_backfill,
                    since_backfill=since_backfill,
                    max_pages=max_pages_per_up,
                )
            except Exception as exc:
                logger.warning("Bilibili UP poll failed mid=%s: %s", up_mid, exc)
                report["errors"].append({"mid": up_mid, "error": str(exc)})
                if _is_bilibili_rate_limit(exc):
                    report["rate_limited"] += 1
                    consecutive_rate_limits += 1
                    cooldown_pending = settings.bilibili_up_poll_rate_limit_cooldown_seconds
                    if consecutive_rate_limits >= settings.bilibili_up_poll_rate_limit_stop_after:
                        report["stopped_early"] = True
                        report["stop_reason"] = "rate_limit"
                        report["ups_deferred"] = len(ups) - index - 1
                        logger.warning(
                            "Bilibili UP poll stopped after %s consecutive rate limits "
                            "(API 频控，建议暂停 1–2 小时后再同步；通常不是封号)",
                            consecutive_rate_limits,
                        )
                        break
                continue

            consecutive_rate_limits = 0

            report["ups_polled"] += 1
            if not videos:
                continue

            if first_run and not effective_backfill and not since_backfill:
                arc = videos[0]
                url = _video_url(arc)
                if url and not _should_skip_url(storage, url):
                    entry_id = str(arc.get("bvid") or url)
                    published = _video_created_iso(arc.get("created"))
                    _enqueue_bilibili_video(
                        storage,
                        url=url,
                        arc=arc,
                        up_mid=up_mid,
                        uname=uname,
                        up_face=str(row.get("face") or "").strip() or None,
                        label=label,
                        title_index=title_index,
                        report=report,
                        initial_snapshot=True,
                        subscription_source=subscription_source,
                    )
                    storage.set_rss_feed_state(
                        cursor_key,
                        last_entry_id=entry_id,
                        last_published=published,
                    )
                elif url:
                    report["skipped_existing"] += 1
                    entry_id = str(arc.get("bvid") or url)
                    storage.set_rss_feed_state(
                        cursor_key,
                        last_entry_id=entry_id,
                        last_published=_video_created_iso(arc.get("created")),
                    )
                continue

            candidates: list[dict[str, Any]] = []
            for arc in videos:
                entry_id = str(arc.get("bvid") or "").strip()
                if not entry_id:
                    continue
                published = _video_created_iso(arc.get("created"))
                created_ts = _video_created_ts(arc.get("created"))
                if sync_since_ts is not None and created_ts is not None and created_ts < sync_since_ts:
                    report["skipped_before_since"] += 1
                    continue
                if effective_backfill or since_backfill:
                    candidates.append(arc)
                elif _is_newer(entry_id, published, last_id, last_published):
                    candidates.append(arc)

            if effective_backfill or since_backfill:
                candidates = list(reversed(candidates[-per_up_limit:]))
            else:
                candidates.reverse()

            newest_id = last_id
            newest_pub = last_published
            for arc in candidates:
                url = _video_url(arc)
                if not url:
                    continue
                entry_id = str(arc.get("bvid") or url)
                published = _video_created_iso(arc.get("created"))
                if _should_skip_url(storage, url):
                    report["skipped_existing"] += 1
                else:
                    _enqueue_bilibili_video(
                        storage,
                        url=url,
                        arc=arc,
                        up_mid=up_mid,
                        uname=uname,
                        up_face=str(row.get("face") or "").strip() or None,
                        label=label,
                        title_index=title_index,
                        report=report,
                        backfill=effective_backfill or since_backfill,
                        subscription_source=subscription_source,
                    )
                if _is_newer(entry_id, published, newest_id, newest_pub):
                    newest_id = entry_id
                    newest_pub = published

            if newest_id:
                storage.set_rss_feed_state(
                    cursor_key,
                    last_entry_id=newest_id,
                    last_published=newest_pub,
                )

    return report


def _enqueue_bilibili_video(
    storage: StoragePort,
    *,
    url: str,
    arc: dict[str, Any],
    up_mid: str,
    uname: str,
    label: str,
    title_index: dict[str, list[int]],
    report: dict[str, Any],
    up_face: str | None = None,
    initial_snapshot: bool = False,
    backfill: bool = False,
    subscription_source: str = "bilibili_up",
) -> None:
    normalized = normalize_bilibili_url(url)
    title = str(arc.get("title") or "").strip()
    duration = arc.get("length") or arc.get("duration")
    try:
        duration_sec = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_sec = None
    description = str(arc.get("description") or arc.get("desc") or "").strip()
    dup_yt = find_youtube_duplicate(
        storage,
        title=title,
        duration_sec=duration_sec,
        description=description,
        title_index=title_index,
    )
    if dup_yt is not None:
        if remove_bilibili_duplicate_of_youtube(storage, normalized):
            report["skipped_youtube_dup"] += 1
        return

    meta = {
        "feed_label": label,
        "up_mid": up_mid,
        "entry_title": title,
        "entry_id": str(arc.get("bvid") or normalized),
        "published": _video_created_iso(arc.get("created")),
        "subscription_source": subscription_source,
    }
    if initial_snapshot:
        meta["initial_snapshot"] = True
    if backfill:
        meta["backfill"] = True
    meta.update(
        author_meta_patch(
            author=uname,
            author_avatar=up_face,
            author_url=f"https://space.bilibili.com/{up_mid}",
            cover_image=str(arc.get("pic") or arc.get("cover") or "").strip() or None,
        )
    )
    enqueue_url(storage, normalized, source=SourceType.RSS, source_meta=meta)
    report["enqueued"] += 1
    from on1y.sync.progress import get_cold_start_progress

    progress = get_cold_start_progress()
    if progress is not None:
        progress.log_item(
            phase="subscriptions",
            title=title,
            platform="bilibili",
            status="enqueued",
            url=normalized,
            detail=uname,
        )


def sync_bilibili_subscriptions(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    sync_config: bool = True,
    poll: bool = True,
    backfill: bool = False,
    dry_run: bool = False,
    sync_since_ts: int | None = None,
    backfill_max_days: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    report: dict[str, Any] = {"platform": "bilibili"}
    if not settings.bilibili_up_sync_enabled and not dry_run:
        report["skipped"] = True
        report["skip_reason"] = "bilibili_up_sync_disabled"
        return report

    followings: list[dict[str, str]] | None = None
    if sync_config:
        if dry_run:
            cookie_path = resolve_cookie_path("bilibili", settings, user_id=user_id)
            followings = fetch_bilibili_followings(settings=settings, cookie_path=cookie_path)
            merge_bilibili_up_feeds_yaml(
                followings,
                feeds_path=resolve_feeds_config_path(settings, user_id=user_id),
                rsshub_base=settings.bilibili_rsshub_base,
                enabled=True,
                dry_run=True,
            )
            report["config"] = {
                "followings_fetched": len(followings),
                "feeds_merged": len(followings),
                "dry_run": True,
            }
        else:
            report["config"] = sync_bilibili_up_config(settings=settings, user_id=user_id)

    if poll and not dry_run:
        if settings.bilibili_up_poll_mode == "dynamic":
            report["poll"] = poll_bilibili_dynamic_updates(
                storage,
                settings=settings,
                backfill=backfill,
                sync_since_ts=sync_since_ts,
                backfill_max_days=backfill_max_days,
                user_id=user_id,
            )
        else:
            if followings is None and sync_config:
                cookie_path = resolve_cookie_path("bilibili", settings, user_id=user_id)
                followings = fetch_bilibili_followings(settings=settings, cookie_path=cookie_path)
            report["poll"] = poll_bilibili_up_updates(
                storage,
                settings=settings,
                followings=followings,
                backfill=backfill,
                sync_since_ts=sync_since_ts,
                backfill_max_days=backfill_max_days,
                user_id=user_id,
            )

    return report
