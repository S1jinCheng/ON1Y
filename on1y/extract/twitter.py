"""X (Twitter) extractor — Playwright with login cookies."""

from __future__ import annotations

from pathlib import Path

from on1y.config import Settings
from on1y.extract.playwright_base import PlaywrightExtractor
from on1y.utils.platform import PLATFORM_TWITTER, detect_platform


class TwitterExtractor(PlaywrightExtractor):
    @property
    def name(self) -> str:
        return PLATFORM_TWITTER

    @property
    def platform_id(self) -> str:
        return PLATFORM_TWITTER

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == PLATFORM_TWITTER

    def cookie_path(self, settings: Settings) -> Path:
        from on1y.cookies.loader import resolve_cookie_path

        return resolve_cookie_path("twitter", settings)

    def seed_domain(self) -> str:
        return ".x.com"

    def wait_selectors(self) -> list[str]:
        return [
            '[data-testid="tweetText"]',
            'article[data-testid="tweet"]',
            "article",
        ]

    def title_selectors(self) -> list[str]:
        return [
            '[data-testid="User-Name"]',
            "h1",
        ]

    def content_selectors(self) -> list[str]:
        # Thread: collect all tweet bodies in order
        return [
            '[data-testid="tweetText"]',
        ]

    def min_body_chars(self) -> int:
        return 1
