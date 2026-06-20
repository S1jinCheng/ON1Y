"""YouTube channel avatar resolution (avoid brittle unavatar.io URLs)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from on1y.config import Settings, get_settings
from on1y.utils.author_meta import author_meta_patch, is_unreliable_avatar_url, resolve_author_avatar

logger = logging.getLogger(__name__)

_CHANNEL_ID_RE = re.compile(r"(?:channel/|/channel/)(UC[\w-]{20,})", re.I)
_AVATAR_URL_RE = re.compile(
    r'"avatar"\s*:\s*\{\s*"thumbnails"\s*:\s*\[\s*\{\s*"url"\s*:\s*"(https://[^"]+)"'
)
_avatar_cache: dict[str, str] = {}


def clear_youtube_avatar_cache() -> None:
    _avatar_cache.clear()


def channel_id_from_meta(meta: dict[str, Any]) -> str:
    cid = str(meta.get("channel_id") or "").strip()
    if cid:
        return cid
    for key in ("author_url", "uploader_url", "channel_url", "profile_url"):
        match = _CHANNEL_ID_RE.search(str(meta.get(key) or ""))
        if match:
            return match.group(1)
    return ""


def _avatar_from_channel_html(html: str) -> str:
    from on1y.utils.youtube_account import (
        _decode_json_string,
        _find_channel_metadata,
        _parse_yt_initial_data,
        _thumbnail_url,
    )

    initial = _parse_yt_initial_data(html)
    if initial:
        meta = _find_channel_metadata(initial)
        if meta:
            url = _thumbnail_url(meta.get("avatar"))
            if url:
                return url
    match = _AVATAR_URL_RE.search(html)
    if not match:
        return ""
    return _decode_json_string(match.group(1))


def fetch_youtube_channel_avatar(
    channel_id: str,
    *,
    settings: Settings | None = None,
) -> str:
    """Resolve channel avatar from the public channel page (cached)."""
    channel_id = str(channel_id or "").strip()
    if not channel_id:
        return ""
    if channel_id in _avatar_cache:
        return _avatar_cache[channel_id]

    settings = settings or get_settings()
    avatar = ""
    url = f"https://www.youtube.com/channel/{channel_id}"
    client_kwargs: dict[str, Any] = {
        "timeout": settings.http_timeout_seconds,
        "follow_redirects": True,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    from on1y.network.proxy import effective_ytdlp_proxy

    proxy = effective_ytdlp_proxy(settings=settings)
    if proxy:
        client_kwargs["proxy"] = proxy
    try:
        with httpx.Client(**client_kwargs) as client:
            response = client.get(url)
            response.raise_for_status()
            avatar = _avatar_from_channel_html(response.text)
    except Exception as exc:
        logger.debug("YouTube avatar page lookup failed channel=%s: %s", channel_id, exc)

    if avatar and not is_unreliable_avatar_url(avatar):
        _avatar_cache[channel_id] = avatar
        return avatar

    _avatar_cache[channel_id] = ""
    return ""


def enrich_youtube_author_meta(
    meta: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Fill author_avatar when missing or using unavatar.io."""
    if not is_unreliable_avatar_url(resolve_author_avatar(meta)):
        return meta
    channel_id = channel_id_from_meta(meta)
    if not channel_id:
        return meta
    avatar = fetch_youtube_channel_avatar(channel_id, settings=settings)
    if avatar:
        meta.update(author_meta_patch(author_avatar=avatar))
    return meta
