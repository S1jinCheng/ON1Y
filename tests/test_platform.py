"""Platform detection tests."""

from on1y.utils.platform import detect_platform, normalize_url


def test_detect_youtube() -> None:
    assert detect_platform("https://www.youtube.com/watch?v=abc") == "youtube"
    assert detect_platform("https://youtu.be/abc") == "youtube"


def test_detect_bilibili() -> None:
    assert detect_platform("https://www.bilibili.com/video/BV1xx") == "bilibili"


def test_detect_generic() -> None:
    assert detect_platform("https://example.com/post/1") == "generic"


def test_normalize_url_strips_fragment() -> None:
    assert (
        normalize_url("https://example.com/a#section")
        == "https://example.com/a"
    )
