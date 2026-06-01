"""Tests for platform-scoped subtitle queue."""

from on1y.utils.platform import PLATFORM_BILIBILI, PLATFORM_YOUTUBE


def test_video_platform_constants() -> None:
    assert PLATFORM_YOUTUBE == "youtube"
    assert PLATFORM_BILIBILI == "bilibili"
