"""Base class for Playwright + cookie authenticated extractors."""

from __future__ import annotations

import abc
import logging
from pathlib import Path

from on1y.browser.playwright_client import PageContent, fetch_page_content
from on1y.browser.playwright_session import PlaywrightSession
from on1y.config import Settings, get_settings
from on1y.extract.base import BaseExtractor
from on1y.models.enums import ContentType
from on1y.models.extract import ExtractResult

logger = logging.getLogger(__name__)


class PlaywrightExtractor(BaseExtractor, abc.ABC):
    """Requires a valid cookie file for the target platform."""

    @property
    @abc.abstractmethod
    def platform_id(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def cookie_path(self, settings: Settings) -> Path:
        raise NotImplementedError

    @abc.abstractmethod
    def seed_domain(self) -> str:
        """Cookie domain, e.g. `.zhihu.com`."""
        raise NotImplementedError

    @abc.abstractmethod
    def wait_selectors(self) -> list[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def title_selectors(self) -> list[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def content_selectors(self) -> list[str]:
        raise NotImplementedError

    def min_body_chars(self) -> int:
        return 20

    def settle_ms(self) -> int | None:
        """Extra wait after navigation (Zhihu SPA needs longer)."""
        return None

    def content_type(self) -> ContentType:
        return ContentType.ARTICLE

    def author_selectors(self) -> list[str]:
        return []

    def avatar_selectors(self) -> list[str]:
        return []

    def author_url_selectors(self) -> list[str]:
        return []

    def extract(self, url: str, *, session: PlaywrightSession | None = None) -> ExtractResult:
        settings = get_settings()
        path = self.cookie_path(settings)
        logger.info("Using Playwright extractor %s with cookies %s", self.platform_id, path)

        page: PageContent = fetch_page_content(
            url,
            cookie_path=path,
            seed_domain=self.seed_domain(),
            wait_selectors=self.wait_selectors(),
            title_selectors=self.title_selectors(),
            content_selectors=self.content_selectors(),
            min_body_chars=self.min_body_chars(),
            settle_ms=self.settle_ms(),
            require_selector=False,
            author_selectors=self.author_selectors(),
            avatar_selectors=self.avatar_selectors(),
            author_url_selectors=self.author_url_selectors(),
            session=session,
        )

        parts: list[str] = []
        if page.title:
            parts.append(f"# {page.title}\n")
        parts.append(page.body_text)
        body = "\n".join(parts).strip()

        return self._ok(
            platform=self.platform_id,
            raw_title=page.title,
            body_text=body,
            content_type=self.content_type(),
            author=page.author,
            author_avatar=page.author_avatar,
            author_url=page.author_url,
        )
