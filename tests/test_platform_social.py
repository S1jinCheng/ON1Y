"""Platform detection for social extractors."""

from on1y.utils.platform import (
    PLATFORM_TWITTER,
    PLATFORM_XIAOHONGSHU,
    PLATFORM_ZHIHU,
    detect_platform,
)


def test_zhihu() -> None:
    assert detect_platform("https://www.zhihu.com/question/1/answer/2") == PLATFORM_ZHIHU
    assert detect_platform("https://zhuanlan.zhihu.com/p/123") == PLATFORM_ZHIHU


def test_xiaohongshu() -> None:
    assert detect_platform("https://www.xiaohongshu.com/explore/abc") == PLATFORM_XIAOHONGSHU
    assert detect_platform("https://xhslink.com/abc") == PLATFORM_XIAOHONGSHU


def test_twitter() -> None:
    assert detect_platform("https://x.com/user/status/1") == PLATFORM_TWITTER
    assert detect_platform("https://twitter.com/user/status/1") == PLATFORM_TWITTER
