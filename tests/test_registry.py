"""Extractor registry resolution tests."""

import pytest
from on1y.exceptions import NoExtractorError
from on1y.extract.article import ArticleExtractor
from on1y.extract.bilibili import BilibiliExtractor
from on1y.extract.registry import ExtractorRegistry
from on1y.extract.twitter import TwitterExtractor
from on1y.extract.xiaohongshu import XiaohongshuExtractor
from on1y.extract.youtube import YouTubeExtractor
from on1y.extract.zhihu import ZhihuExtractor


def test_resolve_youtube() -> None:
    registry = ExtractorRegistry([YouTubeExtractor(), BilibiliExtractor(), ArticleExtractor()])
    ext = registry.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert ext.name == "youtube"


def test_resolve_article_fallback() -> None:
    registry = ExtractorRegistry([YouTubeExtractor(), BilibiliExtractor(), ArticleExtractor()])
    ext = registry.resolve("https://example.com/blog/post")
    assert ext.name == "article"


def test_resolve_zhihu() -> None:
    registry = ExtractorRegistry(
        [YouTubeExtractor(), BilibiliExtractor(), ZhihuExtractor(), ArticleExtractor()]
    )
    assert registry.resolve("https://www.zhihu.com/question/1").name == "zhihu"


def test_resolve_xiaohongshu() -> None:
    registry = ExtractorRegistry(
        [
            YouTubeExtractor(),
            BilibiliExtractor(),
            XiaohongshuExtractor(),
            ArticleExtractor(),
        ]
    )
    assert registry.resolve("https://www.xiaohongshu.com/explore/x").name == "xiaohongshu"


def test_resolve_twitter() -> None:
    registry = ExtractorRegistry(
        [YouTubeExtractor(), BilibiliExtractor(), TwitterExtractor(), ArticleExtractor()]
    )
    assert registry.resolve("https://x.com/a/status/1").name == "twitter"


def test_no_extractor_empty_registry() -> None:
    registry = ExtractorRegistry([])
    with pytest.raises(NoExtractorError):
        registry.resolve("https://example.com")
