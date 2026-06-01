"""Merge yt-dlp / platform author metadata into source_meta without clobbering."""

from __future__ import annotations

import logging
from typing import Any

from on1y.extract.ytdlp_video import get_ytdlp_video_extractor
from on1y.utils.author_meta import author_meta_patch, merge_author_meta, resolve_author_avatar
from on1y.utils.platform import PLATFORM_BILIBILI, YTDLP_VIDEO_PLATFORMS

logger = logging.getLogger(__name__)


def enrich_video_source_meta(
    meta: dict[str, Any] | None,
    *,
    platform: str,
    url: str,
) -> dict[str, Any]:
    """
    Fill author, avatar, cover, channel_id from yt-dlp when absent.
    Bilibili: also resolve UP face via followings API.
    """
    out = dict(meta or {})
    if platform not in YTDLP_VIDEO_PLATFORMS:
        return out

    try:
        vm = get_ytdlp_video_extractor(platform).fetch_metadata(url)
        out = merge_author_meta(
            out,
            author_meta_patch(
                author=vm.uploader,
                author_avatar=vm.uploader_avatar,
                author_url=vm.uploader_url,
                cover_image=vm.cover_image,
                channel_id=vm.channel_id,
            ),
        )
    except Exception as exc:
        logger.debug("Video metadata enrich skipped for %s: %s", url, exc)

    if platform == PLATFORM_BILIBILI:
        from on1y.utils.bilibili_author import enrich_bilibili_author_meta

        enrich_bilibili_author_meta(out)

    return out
