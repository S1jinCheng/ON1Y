"""Cross-platform video deduplication (prefer Bilibili over YouTube)."""

from __future__ import annotations

import re
from typing import Any

from on1y.ports.storage import StoragePort
from on1y.utils.bilibili_url import normalize_bilibili_url
from on1y.utils.platform import PLATFORM_YOUTUBE, normalize_url

_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)
_TITLE_CLEAN_RE = re.compile(r"[^\w\s\u4e00-\u9fff]+", re.UNICODE)
_DURATION_TOLERANCE = 0.05


def normalize_video_title(title: str | None) -> str:
    text = str(title or "").strip()
    text = _TITLE_CLEAN_RE.sub("", text)
    return re.sub(r"\s+", "", text).lower()


def extract_youtube_video_ids(text: str | None) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _YOUTUBE_ID_RE.finditer(text):
        vid = match.group(1)
        if vid not in seen:
            seen.add(vid)
            ordered.append(vid)
    return ordered


def youtube_urls_for_id(video_id: str) -> list[str]:
    vid = str(video_id or "").strip()
    if not vid:
        return []
    return [
        f"https://www.youtube.com/watch?v={vid}",
        f"https://youtu.be/{vid}",
    ]


def _duration_close(a: int | None, b: int | None) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    ratio = abs(a - b) / max(a, b)
    return ratio <= _DURATION_TOLERANCE


def youtube_title_index(storage: StoragePort) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    if not hasattr(storage, "_connect"):
        return index
    conn = storage._connect()
    rows = conn.execute(
        "SELECT id, raw_title FROM raw_items WHERE platform = ? AND deleted_at IS NULL",
        (PLATFORM_YOUTUBE,),
    ).fetchall()
    for row in rows:
        key = normalize_video_title(row["raw_title"])
        if not key:
            continue
        index.setdefault(key, []).append(int(row["id"]))
    return index


def bilibili_title_index(storage: StoragePort) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    if not hasattr(storage, "_connect"):
        return index
    conn = storage._connect()
    rows = conn.execute(
        "SELECT id, raw_title FROM raw_items WHERE platform = ? AND deleted_at IS NULL",
        ("bilibili",),
    ).fetchall()
    for row in rows:
        key = normalize_video_title(row["raw_title"])
        if not key:
            continue
        index.setdefault(key, []).append(int(row["id"]))
    return index


def _item_meta(conn, raw_id: int) -> dict[str, Any]:
    import json

    row = conn.execute("SELECT source_meta FROM raw_items WHERE id = ?", (raw_id,)).fetchone()
    if row is None:
        return {}
    try:
        meta = json.loads(row["source_meta"] or "{}")
    except json.JSONDecodeError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _youtube_meta(conn, raw_id: int) -> dict[str, Any]:
    return _item_meta(conn, raw_id)


def _bilibili_meta(conn, raw_id: int) -> dict[str, Any]:
    return _item_meta(conn, raw_id)


def find_bilibili_duplicate(
    storage: StoragePort,
    *,
    title: str | None,
    duration_sec: int | None = None,
    title_index: dict[str, list[int]] | None = None,
) -> int | None:
    """Return bilibili raw_id when a YouTube item duplicates an existing Bilibili video."""
    key = normalize_video_title(title)
    if not key:
        return None

    index = title_index if title_index is not None else bilibili_title_index(storage)
    candidates = index.get(key) or []
    if not candidates:
        return None
    if len(candidates) == 1 and duration_sec is None:
        return int(candidates[0])

    if duration_sec is None:
        return None

    conn = storage._connect() if hasattr(storage, "_connect") else None
    for raw_id in candidates:
        if conn is None:
            return int(raw_id)
        meta = _bilibili_meta(conn, int(raw_id))
        bili_duration = meta.get("duration_sec")
        if isinstance(bili_duration, (int, float)):
            if _duration_close(int(duration_sec), int(bili_duration)):
                return int(raw_id)
        elif len(candidates) == 1:
            return int(raw_id)
    return None


def find_youtube_duplicate(
    storage: StoragePort,
    *,
    title: str | None,
    duration_sec: int | None = None,
    description: str | None = None,
    title_index: dict[str, list[int]] | None = None,
) -> int | None:
    """
    Return youtube raw_id if this Bilibili item duplicates an existing YouTube item.
    Matches via YouTube links in text, then normalized title (+ duration when available).
    """
    text = f"{description or ''}"
    for video_id in extract_youtube_video_ids(text):
        for yt_url in youtube_urls_for_id(video_id):
            existing = storage.get_raw_by_url(normalize_url(yt_url))
            if existing is not None and existing.platform == PLATFORM_YOUTUBE:
                return int(existing.id)

    key = normalize_video_title(title)
    if not key:
        return None

    index = title_index if title_index is not None else youtube_title_index(storage)
    candidates = index.get(key) or []
    if not candidates:
        return None
    if len(candidates) == 1 and duration_sec is None:
        return int(candidates[0])

    if duration_sec is None:
        return None

    conn = storage._connect() if hasattr(storage, "_connect") else None
    for raw_id in candidates:
        if conn is None:
            return int(raw_id)
        meta = _youtube_meta(conn, int(raw_id))
        yt_duration = meta.get("duration_sec")
        if isinstance(yt_duration, (int, float)):
            if _duration_close(int(duration_sec), int(yt_duration)):
                return int(raw_id)
        elif len(candidates) == 1:
            return int(raw_id)
    return None


def remove_youtube_duplicate_by_id(
    storage: StoragePort,
    youtube_raw_id: int,
    *,
    dry_run: bool = False,
) -> bool:
    """Delete a YouTube raw_item by id. Returns True if deleted."""
    if dry_run:
        return True
    if not hasattr(storage, "delete_raw_item"):
        return False
    storage.delete_raw_item(int(youtube_raw_id))
    return True


def remove_youtube_duplicate_of_bilibili(
    storage: StoragePort,
    youtube_url: str,
    *,
    dry_run: bool = False,
) -> bool:
    """Delete an existing YouTube raw_item if present. Returns True if deleted."""
    existing = storage.get_raw_by_url(normalize_url(youtube_url))
    if existing is None or existing.platform != PLATFORM_YOUTUBE:
        return False
    return remove_youtube_duplicate_by_id(storage, int(existing.id), dry_run=dry_run)


def purge_youtube_duplicates_of_bilibili(
    storage: StoragePort,
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """One-pass cleanup: drop YouTube items that duplicate a Bilibili title (+ duration)."""
    stats = {"scanned": 0, "removed": 0}
    if not hasattr(storage, "_connect"):
        return stats
    conn = storage._connect()
    bili_index = bilibili_title_index(storage)
    rows = conn.execute(
        """
        SELECT id, raw_title, source_meta
        FROM raw_items
        WHERE platform = ? AND deleted_at IS NULL
        ORDER BY id ASC
        """,
        (PLATFORM_YOUTUBE,),
    ).fetchall()
    for row in rows:
        stats["scanned"] += 1
        raw_id = int(row["id"])
        meta = _item_meta(conn, raw_id)
        duration = meta.get("duration_sec")
        try:
            duration_sec = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_sec = None
        key = normalize_video_title(str(row["raw_title"] or ""))
        if not key:
            continue
        candidates = bili_index.get(key) or []
        if not candidates:
            continue
        should_remove = False
        if len(candidates) == 1:
            if duration_sec is None:
                should_remove = True
            else:
                bili_meta = _bilibili_meta(conn, int(candidates[0]))
                bili_duration = bili_meta.get("duration_sec")
                if isinstance(bili_duration, (int, float)):
                    should_remove = _duration_close(duration_sec, int(bili_duration))
                else:
                    should_remove = True
        elif duration_sec is not None:
            for bili_id in candidates:
                bili_meta = _bilibili_meta(conn, int(bili_id))
                bili_duration = bili_meta.get("duration_sec")
                if isinstance(bili_duration, (int, float)) and _duration_close(
                    duration_sec, int(bili_duration)
                ):
                    should_remove = True
                    break
        if should_remove and remove_youtube_duplicate_by_id(storage, raw_id, dry_run=dry_run):
            stats["removed"] += 1
    return stats


def remove_bilibili_duplicate_of_youtube(
    storage: StoragePort,
    bilibili_url: str,
    *,
    dry_run: bool = False,
) -> bool:
    """Delete an existing Bilibili raw_item if present. Returns True if deleted."""
    normalized = normalize_bilibili_url(bilibili_url)
    existing = storage.get_raw_by_url(normalized)
    if existing is None or existing.platform != "bilibili":
        return False
    if dry_run:
        return True
    storage.delete_raw_item(int(existing.id))
    return True
