"""Reusable Playwright browser session for batch page fetches."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from on1y.browser.cookies import load_cookie_file
from on1y.browser.playwright_client import (
    PageContent,
    _create_context,
    _extract_page_content,
)
from on1y.config import get_settings
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class PlaywrightSession:
    """One browser + context; open a fresh page per URL."""

    def __init__(
        self,
        *,
        cookie_path: Path,
        seed_domain: str,
        headless: bool | None = None,
    ) -> None:
        self._cookie_path = cookie_path
        self._seed_domain = seed_domain
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    def __enter__(self) -> PlaywrightSession:
        settings = get_settings()
        cookie_data = load_cookie_file(self._cookie_path)
        headless = settings.playwright_headless if self._headless is None else self._headless

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ConfigurationError(
                "Playwright is not installed. Run: pip install playwright "
                "&& playwright install chromium"
            ) from exc

        from on1y.browser.discover import STEALTH_INIT_SCRIPT, launch_playwright_chromium

        self._playwright = sync_playwright().start()
        self._browser = launch_playwright_chromium(self._playwright, headless=headless)
        self._context = _create_context(self._browser, cookie_data, seed_domain=self._seed_domain)
        self._context.add_init_script(STEALTH_INIT_SCRIPT)
        logger.info("Playwright session started (seed=%s)", self._seed_domain)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        logger.info("Playwright session closed")

    def fetch_page(
        self,
        url: str,
        *,
        wait_selectors: list[str],
        title_selectors: list[str] | None = None,
        content_selectors: list[str],
        min_body_chars: int = 20,
        settle_ms: int | None = None,
        require_selector: bool = False,
        author_selectors: list[str] | None = None,
        avatar_selectors: list[str] | None = None,
        author_url_selectors: list[str] | None = None,
    ) -> PageContent:
        if self._context is None:
            raise ConfigurationError("PlaywrightSession is not started; use `with` block")

        settings = get_settings()
        page = self._context.new_page()
        page.set_default_timeout(settings.playwright_timeout_ms)
        try:
            logger.info("Playwright navigating to %s", url)
            return _extract_page_content(
                page,
                url,
                wait_selectors=wait_selectors,
                title_selectors=title_selectors,
                content_selectors=content_selectors,
                min_body_chars=min_body_chars,
                settle_ms=settle_ms,
                require_selector=require_selector,
                author_selectors=author_selectors,
                avatar_selectors=avatar_selectors,
                author_url_selectors=author_url_selectors,
            )
        finally:
            page.close()
