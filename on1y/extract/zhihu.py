"""Zhihu extractor — Playwright with login cookies."""

from __future__ import annotations

from pathlib import Path

from on1y.config import Settings
from on1y.extract.playwright_base import PlaywrightExtractor
from on1y.utils.platform import PLATFORM_ZHIHU, detect_platform


class ZhihuExtractor(PlaywrightExtractor):
    @property
    def name(self) -> str:
        return PLATFORM_ZHIHU

    @property
    def platform_id(self) -> str:
        return PLATFORM_ZHIHU

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == PLATFORM_ZHIHU

    def cookie_path(self, settings: Settings) -> Path:
        return settings.zhihu_cookies_path

    def seed_domain(self) -> str:
        return ".zhihu.com"

    def settle_ms(self) -> int:
        return 4000

    def wait_selectors(self) -> list[str]:
        # Zhihu SPA — many layouts; soft-wait tries all, then extracts anyway
        return [
            ".RichContent-inner",
            ".RichContent",
            "[itemprop='text']",
            ".AnswerItem",
            ".QuestionAnswer-content",
            ".Question-main",
            ".ContentItem.AnswerItem",
            "h1.QuestionHeader-title",
            "article",
            ".App-main",
        ]

    def title_selectors(self) -> list[str]:
        return [
            "h1.QuestionHeader-title",
            "h1[data-za-detail='title']",
            "h1.Post-Title",
            "h1",
            ".QuestionHeader-title",
        ]

    def content_selectors(self) -> list[str]:
        return [
            ".RichContent-inner",
            ".RichContent",
            "[itemprop='text']",
            ".AnswerItem .RichContent",
            ".OriginAnswer .RichContent-inner",
            ".Post-RichText",
            ".RichText",
            "article",
        ]

    def min_body_chars(self) -> int:
        return 30

    def author_selectors(self) -> list[str]:
        return [
            ".AuthorInfo-name .UserLink-link",
            ".AuthorInfo-name",
            ".ContentItem-meta .UserLink-link",
            ".UserLink-link",
        ]

    def avatar_selectors(self) -> list[str]:
        return [
            ".AuthorInfo-avatar img",
            ".AuthorInfo-avatarImg",
            "img.Avatar",
            ".Avatar img",
        ]

    def author_url_selectors(self) -> list[str]:
        return [
            ".AuthorInfo-name .UserLink-link",
            ".AuthorInfo-name a",
            ".ContentItem-meta .UserLink-link",
        ]
