"""Tests for permanently unavailable video detection."""

from __future__ import annotations

from on1y.utils.video_unavailable import is_bilibili_video_unavailable, is_permanent_video_error


def test_bilibili_unavailable_messages() -> None:
    assert is_bilibili_video_unavailable("yt-dlp metadata error: 视频不存在")
    assert is_bilibili_video_unavailable("BiliBili says: 啥都木有")
    assert is_bilibili_video_unavailable("HTTP Error 404: Not Found")
    assert is_bilibili_video_unavailable("Private video. Sign in if you've been granted access.")


def test_bilibili_transient_errors_not_matched() -> None:
    assert not is_bilibili_video_unavailable("HTTP Error 429: Too Many Requests")
    assert not is_bilibili_video_unavailable("Connection timed out")
    assert not is_bilibili_video_unavailable("")


def test_permanent_video_error_platform() -> None:
    assert is_permanent_video_error("视频已失效", "bilibili")
    assert not is_permanent_video_error("视频已失效", "youtube")
