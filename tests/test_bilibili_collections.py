"""Tests for Bilibili URL + cross-platform dedup helpers."""

from on1y.utils.bilibili_url import bilibili_video_url, normalize_bilibili_url
from on1y.utils.video_dedup import extract_youtube_video_ids, normalize_video_title


def test_normalize_bilibili_url() -> None:
    assert (
        normalize_bilibili_url("https://www.bilibili.com/video/BV1xx4111xxx/?p=2")
        == "https://www.bilibili.com/video/BV1xx4111xxx?p=2"
    )
    assert normalize_bilibili_url("https://www.bilibili.com/video/bv1xx4111xxx/") == (
        "https://www.bilibili.com/video/BV1xx4111xxx"
    )


def test_bilibili_video_url() -> None:
    assert bilibili_video_url("BV1234567890") == "https://www.bilibili.com/video/BV1234567890"


def test_extract_youtube_video_ids() -> None:
    text = "搬运自 https://www.youtube.com/watch?v=dQw4w9WgXcQ 感谢"
    assert extract_youtube_video_ids(text) == ["dQw4w9WgXcQ"]


def test_normalize_video_title() -> None:
    assert normalize_video_title("Hello, World!") == normalize_video_title("hello world")
