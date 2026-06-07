"""Detect permanently unavailable video URLs (no point retrying ingest/subtitles)."""

from __future__ import annotations

import re

from on1y.utils.platform import PLATFORM_BILIBILI

_BILIBILI_UNAVAILABLE_RE = re.compile(
    r"视频不存在|稿件不存在|视频已失效|该视频不可见|作品已被删除|"
    r"资源已失效|已被.{0,12}删除|无权限查看|内容不存在|"
    r"啥都木有|Did not get any data blocks|"
    r"Private video|video is unavailable|Video unavailable|"
    r"HTTP Error 404:\s*Not Found|unable to extract embedded player|"
    r"此视频.{0,16}不可用|该稿件.{0,16}不存在|"
    r"copyright|版权|因版权",
    re.IGNORECASE,
)


def is_bilibili_video_unavailable(message: str) -> bool:
    """True when yt-dlp / Bilibili API indicates the video is gone or inaccessible."""
    if not message or not str(message).strip():
        return False
    return bool(_BILIBILI_UNAVAILABLE_RE.search(message))


def is_permanent_video_error(message: str, platform: str) -> bool:
    if platform == PLATFORM_BILIBILI:
        return is_bilibili_video_unavailable(message)
    return False
