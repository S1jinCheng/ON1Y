"""Extractor registry — first matching handler wins."""

from __future__ import annotations

import logging

from on1y.exceptions import ExtractionError, NoExtractorError
from on1y.extract.article import ArticleExtractor
from on1y.extract.bilibili import BilibiliExtractor
from on1y.extract.twitter import TwitterExtractor
from on1y.extract.xiaohongshu import XiaohongshuExtractor
from on1y.extract.youtube import YouTubeExtractor
from on1y.extract.zhihu import ZhihuExtractor
from on1y.models.extract import ExtractResult
from on1y.ports.extractor import ExtractorPort
from on1y.utils.platform import normalize_url

logger = logging.getLogger(__name__)


class ExtractorRegistry:
    def __init__(self, extractors: list[ExtractorPort] | None = None) -> None:
        self._extractors: list[ExtractorPort] = extractors or []

    def register(self, extractor: ExtractorPort) -> None:
        self._extractors.append(extractor)

    def resolve(self, url: str) -> ExtractorPort:
        normalized = normalize_url(url)
        for extractor in self._extractors:
            if extractor.can_handle(normalized):
                logger.debug("Resolved extractor %s for %s", extractor.name, normalized)
                return extractor
        raise NoExtractorError(
            f"No extractor registered for URL: {url}",
            url=url,
            platform=None,
        )

    def extract(self, url: str) -> ExtractResult:
        normalized = normalize_url(url)
        extractor = self.resolve(normalized)
        try:
            return extractor.extract(normalized)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(
                str(exc),
                url=normalized,
                platform=extractor.name,
            ) from exc


_default_registry: ExtractorRegistry | None = None


def get_default_registry() -> ExtractorRegistry:
    global _default_registry
    if _default_registry is None:
        registry = ExtractorRegistry()
        # Order matters: specific platforms before generic article handler.
        registry.register(YouTubeExtractor())
        registry.register(BilibiliExtractor())
        registry.register(ZhihuExtractor())
        registry.register(XiaohongshuExtractor())
        registry.register(TwitterExtractor())
        registry.register(ArticleExtractor())
        _default_registry = registry
    return _default_registry
