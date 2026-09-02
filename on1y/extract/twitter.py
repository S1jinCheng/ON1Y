"""X (Twitter) extractor — Playwright with login cookies."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from on1y.config import Settings, get_settings
from on1y.extract.playwright_base import PlaywrightExtractor
from on1y.models.extract import ExtractResult
from on1y.utils.platform import PLATFORM_TWITTER, detect_platform

if TYPE_CHECKING:
    from on1y.browser.playwright_session import PlaywrightSession


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
        return ['[data-testid="tweetText"]']

    def settle_ms(self) -> int | None:
        return 3000

    def author_selectors(self) -> list[str]:
        return ['[data-testid="User-Name"]', '[data-testid="User-Names"]']

    def avatar_selectors(self) -> list[str]:
        return ['[data-testid="Tweet-User-Avatar"] img', 'img[src*="profile_images"]']

    def author_url_selectors(self) -> list[str]:
        return ['[data-testid="User-Name"] a', 'a[href^="/"][role="link"]']

    def min_body_chars(self) -> int:
        return 1

    def extract(self, url: str, *, session: PlaywrightSession | None = None) -> ExtractResult:
        """Extract one status as Markdown: tweet text, quote/retweet blocks, media links only."""
        from on1y.browser.twitter_playwright import fetch_twitter_status_markdown

        settings = get_settings()
        extracted = fetch_twitter_status_markdown(
            url,
            cookie_path=self.cookie_path(settings),
            seed_domain=self.seed_domain(),
            settle_ms=self.settle_ms(),
            session=session,
            settings=settings,
        )
        return self._ok(
            platform=self.platform_id,
            raw_title=extracted.raw_title,
            body_text=extracted.body_text,
            content_type=self.content_type(),
            author=extracted.author,
            author_avatar=extracted.author_avatar,
            author_url=extracted.author_url,
            source_meta={
                "twitter_kind": extracted.kind,
                "twitter_status_url": extracted.status_url,
                "published": extracted.published,
                "social_stats": extracted.social_stats or {},
            },
        )
