"""Bilibili UP avatar resolution when yt-dlp omits uploader_thumbnail."""

from __future__ import annotations

import re
from typing import Any

from on1y.config import Settings, get_settings
from on1y.utils.author_meta import author_meta_patch, resolve_author_avatar

_face_cache: dict[str, str] | None = None

_SPACE_MID_RE = re.compile(r"space\.bilibili\.com/(\d+)", re.I)


def clear_bilibili_face_cache() -> None:
    global _face_cache
    _face_cache = None


def bilibili_up_faces(*, settings: Settings | None = None, refresh: bool = False) -> dict[str, str]:
    """Map UP mid -> face URL from the logged-in followings list."""
    global _face_cache
    if _face_cache is not None and not refresh:
        return _face_cache
    from on1y.ingestion.bilibili_api import fetch_bilibili_followings

    rows = fetch_bilibili_followings(settings=settings or get_settings())
    _face_cache = {
        str(row["mid"]): str(row["face"]).strip()
        for row in rows
        if row.get("mid") and str(row.get("face") or "").strip()
    }
    return _face_cache


def up_mid_from_meta(meta: dict[str, Any]) -> str:
    up_mid = str(meta.get("up_mid") or "").strip()
    if up_mid:
        return up_mid
    match = _SPACE_MID_RE.search(str(meta.get("author_url") or ""))
    return match.group(1) if match else ""


def _face_for_up_mid(up_mid: str, *, settings: Settings | None = None) -> str:
    face = bilibili_up_faces(settings=settings).get(up_mid)
    if face:
        return face
    from on1y.ingestion.bilibili_api import fetch_bilibili_up_face

    return fetch_bilibili_up_face(up_mid, settings=settings) or ""


def enrich_bilibili_author_meta(meta: dict[str, Any], *, settings: Settings | None = None) -> dict[str, Any]:
    """Fill author_avatar from followings API when missing."""
    if resolve_author_avatar(meta):
        return meta
    up_mid = up_mid_from_meta(meta)
    if not up_mid:
        return meta
    face = _face_for_up_mid(up_mid, settings=settings)
    if face:
        meta.update(author_meta_patch(author_avatar=face))
    return meta
