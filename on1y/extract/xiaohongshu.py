"""Xiaohongshu (RedNote) extractor — Playwright with login cookies."""

from __future__ import annotations

from pathlib import Path

from on1y.config import Settings
from on1y.extract.playwright_base import PlaywrightExtractor
from on1y.utils.platform import PLATFORM_XIAOHONGSHU, detect_platform


class XiaohongshuExtractor(PlaywrightExtractor):
    @property
    def name(self) -> str:
        return PLATFORM_XIAOHONGSHU

    @property
    def platform_id(self) -> str:
        return PLATFORM_XIAOHONGSHU

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == PLATFORM_XIAOHONGSHU

    def cookie_path(self, settings: Settings) -> Path:
        return settings.xiaohongshu_cookies_path

    def seed_domain(self) -> str:
        return ".xiaohongshu.com"

    def wait_selectors(self) -> list[str]:
        return [
            "#detail-desc",
            ".note-text",
            ".desc",
            ".title",
            '[class*="note-content"]',
            "main",
        ]

    def title_selectors(self) -> list[str]:
        return [
            "#detail-title",
            ".title",
            "h1",
        ]

    def content_selectors(self) -> list[str]:
        return [
            "#detail-desc",
            ".note-text",
            ".desc",
            '[class*="note-content"]',
            "#detail-title",
        ]

    def min_body_chars(self) -> int:
        return 5
