"""Normalize author / cover fields from source_meta."""

from __future__ import annotations

from typing import Any

from on1y.extract.ytdlp_meta import youtube_channel_avatar_url

_YT_VIDEO_THUMB = "/vi/"


def _is_video_thumbnail(url: str) -> bool:
    return _YT_VIDEO_THUMB in url


def resolve_author_avatar(meta: dict[str, Any]) -> str:
    for key in ("author_avatar", "avatar", "avatar_url", "uploader_avatar", "channel_avatar"):
        value = str(meta.get(key) or "").strip()
        if value and not _is_video_thumbnail(value):
            return value
    channel_id = str(meta.get("channel_id") or "").strip()
    if channel_id:
        return youtube_channel_avatar_url(channel_id) or ""
    return ""


def author_fields_from_meta(meta: dict[str, Any] | None) -> dict[str, str]:
    meta = meta or {}
    name = str(
        meta.get("author")
        or meta.get("uploader")
        or meta.get("owner")
        or meta.get("channel")
        or meta.get("author_name")
        or ""
    ).strip()
    avatar = resolve_author_avatar(meta)
    profile_url = str(
        meta.get("author_url")
        or meta.get("uploader_url")
        or meta.get("channel_url")
        or meta.get("profile_url")
        or ""
    ).strip()
    cover = str(
        meta.get("cover_image")
        or meta.get("thumbnail")
        or meta.get("cover_url")
        or ""
    ).strip()
    if not cover:
        legacy = str(meta.get("author_avatar") or "").strip()
        if legacy and _is_video_thumbnail(legacy):
            cover = legacy
    return {
        "author": name,
        "author_avatar": avatar,
        "author_url": profile_url,
        "cover_image": cover,
        "channel_id": str(meta.get("channel_id") or "").strip(),
    }


def author_meta_patch(
    *,
    author: str | None = None,
    author_avatar: str | None = None,
    author_url: str | None = None,
    cover_image: str | None = None,
    channel_id: str | None = None,
) -> dict[str, str]:
    patch: dict[str, str] = {}
    if author and author.strip():
        patch["author"] = author.strip()
    if author_avatar and author_avatar.strip() and not _is_video_thumbnail(author_avatar):
        patch["author_avatar"] = author_avatar.strip()
    if author_url and author_url.strip():
        patch["author_url"] = author_url.strip()
    if cover_image and cover_image.strip():
        patch["cover_image"] = cover_image.strip()
    if channel_id and channel_id.strip():
        patch["channel_id"] = channel_id.strip()
    return patch


_AUTHOR_META_KEYS = frozenset(
    {"author", "author_avatar", "author_url", "cover_image", "channel_id"}
)


def merge_author_meta(
    base: dict[str, Any] | None,
    patch: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fill empty author/cover fields in base; never overwrite non-empty values."""
    out = dict(base or {})
    if not patch:
        return out
    for key, value in patch.items():
        if key not in _AUTHOR_META_KEYS:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        if key == "author_avatar" and _is_video_thumbnail(text):
            continue
        existing = str(out.get(key) or "").strip()
        if existing:
            if key == "author_avatar" and _is_video_thumbnail(existing):
                out[key] = text
            continue
        out[key] = text
    return out
