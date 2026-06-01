"""Fetch all items from Bilibili 收藏夹 via logged-in API and enqueue for ingest."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.ingestion.bilibili_api import (
    DEFAULT_HEADERS,
    _cookie_jar,
    fetch_bilibili_favlists,
    iter_favlist_items,
)
from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import ExtractStatus, SourceType
from on1y.ports.storage import StoragePort
from on1y.utils.author_meta import author_meta_patch
from on1y.utils.bilibili_url import bilibili_video_url, normalize_bilibili_url
from on1y.utils.platform import normalize_url
from on1y.utils.video_dedup import (
    find_youtube_duplicate,
    remove_bilibili_duplicate_of_youtube,
)

logger = logging.getLogger(__name__)


def slug_label(folder_id: str) -> str:
    return f"bilibili-fav-{folder_id}"


def media_to_url(media: dict[str, Any]) -> str | None:
    bvid = str(media.get("bvid") or media.get("bv_id") or "").strip()
    if not bvid:
        return None
    page = media.get("page")
    try:
        page_num = int(page) if page else 0
    except (TypeError, ValueError):
        page_num = 0
    return normalize_bilibili_url(bilibili_video_url(bvid, page=page_num if page_num > 1 else None))


def author_meta_from_media(media: dict[str, Any]) -> dict[str, str]:
    upper = media.get("upper") or {}
    if not isinstance(upper, dict):
        return {}
    mid = str(upper.get("mid") or "").strip()
    author_url = f"https://space.bilibili.com/{mid}" if mid else None
    return author_meta_patch(
        author=str(upper.get("name") or "").strip() or None,
        author_avatar=str(upper.get("face") or "").strip() or None,
        author_url=author_url,
        cover_image=str(media.get("cover") or "").strip() or None,
    )


def _should_skip_url(storage: StoragePort, url: str) -> bool:
    normalized = normalize_bilibili_url(url)
    raw = storage.get_raw_by_url(normalized)
    if raw is not None and raw.extract_status in (ExtractStatus.OK, ExtractStatus.PARTIAL):
        return True
    if hasattr(storage, "url_in_rss_queue"):
        return storage.url_in_rss_queue(normalized)
    return False


def backfill_bilibili_collections(
    storage: StoragePort,
    *,
    folder_ids: list[str] | None = None,
    dry_run: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Enqueue all videos from the user's Bilibili 收藏夹 (or selected folder IDs)."""
    settings = settings or get_settings()
    favlists = fetch_bilibili_favlists(settings=settings)
    if folder_ids:
        wanted = {str(item) for item in folder_ids}
        favlists = [f for f in favlists if str(f["id"]) in wanted]
        if not favlists:
            raise ConfigurationError(f"No matching Bilibili favlists for ids: {sorted(wanted)}")

    path = settings.bilibili_cookies_path
    jar = _cookie_jar(path)
    if not jar.get("SESSDATA"):
        raise ConfigurationError(f"No bilibili.com cookies in {path}")

    from on1y.utils.video_dedup import youtube_title_index

    title_index = youtube_title_index(storage)

    report: dict[str, Any] = {
        "folders": [],
        "enqueued": 0,
        "skipped_existing": 0,
        "skipped_duplicate": 0,
        "skipped_duplicate_deleted": 0,
        "skipped_non_video": 0,
        "unique_urls": 0,
    }
    seen_urls: set[str] = set()

    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        for fav in favlists:
            folder_id = str(fav["id"])
            folder_name = str(fav.get("title") or folder_id)
            feed_label = slug_label(folder_id)
            coll_stats = {
                "id": folder_id,
                "name": folder_name,
                "total": 0,
                "enqueued": 0,
                "skipped_existing": 0,
                "skipped_duplicate": 0,
                "skipped_duplicate_deleted": 0,
                "skipped_non_video": 0,
                "skipped_duplicate_cross_folder": 0,
            }
            for media in iter_favlist_items(folder_id, settings=settings, client=client):
                if int(media.get("type") or 2) != 2:
                    coll_stats["skipped_non_video"] += 1
                    report["skipped_non_video"] += 1
                    continue
                url = media_to_url(media)
                if not url:
                    coll_stats["skipped_non_video"] += 1
                    report["skipped_non_video"] += 1
                    continue
                coll_stats["total"] += 1
                if url in seen_urls:
                    coll_stats["skipped_duplicate_cross_folder"] += 1
                    continue
                seen_urls.add(url)

                intro = str(media.get("intro") or "")
                link = str(media.get("link") or "")
                duration = media.get("duration")
                try:
                    duration_sec = int(duration) if duration is not None else None
                except (TypeError, ValueError):
                    duration_sec = None

                dup_yt = find_youtube_duplicate(
                    storage,
                    title=str(media.get("title") or ""),
                    duration_sec=duration_sec,
                    description=f"{intro}\n{link}",
                    title_index=title_index,
                )
                if dup_yt is not None:
                    coll_stats["skipped_duplicate"] += 1
                    report["skipped_duplicate"] += 1
                    if remove_bilibili_duplicate_of_youtube(storage, url, dry_run=dry_run):
                        coll_stats["skipped_duplicate_deleted"] += 1
                        report["skipped_duplicate_deleted"] += 1
                    continue

                if _should_skip_url(storage, url):
                    coll_stats["skipped_existing"] += 1
                    report["skipped_existing"] += 1
                    continue

                if dry_run:
                    coll_stats["enqueued"] += 1
                    report["enqueued"] += 1
                    continue

                meta = {
                    "feed_label": feed_label,
                    "folder_id": folder_id,
                    "folder_name": folder_name,
                    "entry_title": media.get("title"),
                    "bvid": media.get("bvid") or media.get("bv_id"),
                    "duration_sec": duration_sec,
                    "backfill": True,
                    "source": "bilibili_fav_api",
                }
                meta.update(author_meta_from_media(media))
                enqueue_url(storage, url, source=SourceType.RSS, source_meta=meta)
                coll_stats["enqueued"] += 1
                report["enqueued"] += 1

            logger.info(
                "Bilibili folder %s (%s): total=%s enqueued=%s skip=%s dup=%s",
                folder_name,
                folder_id,
                coll_stats["total"],
                coll_stats["enqueued"],
                coll_stats["skipped_existing"],
                coll_stats["skipped_duplicate"],
            )
            report["folders"].append(coll_stats)

    report["unique_urls"] = len(seen_urls)
    report["queue_pending"] = (
        storage.count_pending_for_platform("bilibili")
        if hasattr(storage, "count_pending_for_platform")
        else None
    )
    return report
