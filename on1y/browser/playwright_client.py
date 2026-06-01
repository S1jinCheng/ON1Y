"""Playwright page fetch with authenticated session."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from on1y.config import get_settings
from on1y.exceptions import ConfigurationError

if TYPE_CHECKING:
    from on1y.browser.playwright_session import PlaywrightSession

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_LOGIN_WALL_PATTERNS = re.compile(
    r"登录知乎|登录后查看|请您登录|Sign In|扫码登录",
    re.IGNORECASE,
)

_ANTI_BOT_PATTERNS = re.compile(
    r"安全验证|网络环境存在异常|开始验证|/account/unhuman|blocked automated browser",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PageContent:
    url: str
    title: str | None
    body_text: str
    author: str | None = None
    author_avatar: str | None = None
    author_url: str | None = None
    extra: dict[str, Any] | None = None


def is_playwright_antibot_error(message: str) -> bool:
    return bool(_ANTI_BOT_PATTERNS.search(message))


def fetch_page_content(
    url: str,
    *,
    cookie_path: Path,
    seed_domain: str,
    wait_selectors: list[str],
    title_selectors: list[str] | None = None,
    content_selectors: list[str],
    min_body_chars: int = 20,
    settle_ms: int | None = None,
    require_selector: bool = False,
    author_selectors: list[str] | None = None,
    avatar_selectors: list[str] | None = None,
    author_url_selectors: list[str] | None = None,
    session: PlaywrightSession | None = None,
) -> PageContent:
    """
    Open URL in Chromium with cookies, wait for page, extract text.
    By default uses soft-wait (does not fail if CSS selectors change).
    Pass `session` to reuse one browser across multiple URLs.
    """
    if session is not None:
        return session.fetch_page(
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

    from on1y.browser.playwright_session import PlaywrightSession

    with PlaywrightSession(cookie_path=cookie_path, seed_domain=seed_domain) as sess:
        return sess.fetch_page(
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


def _extract_page_content(
    page: Any,
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
    settings = get_settings()
    title_selectors = title_selectors or ["h1", "title"]
    settle = settle_ms if settle_ms is not None else settings.playwright_settle_ms

    page.goto(url, wait_until="domcontentloaded", timeout=settings.playwright_timeout_ms)
    _wait_for_content(page, wait_selectors, require_selector=require_selector)
    page.wait_for_timeout(settle)
    _trigger_lazy_render(page)

    final_url = page.url
    title = _first_inner_text(page, title_selectors)
    body = _extract_combined_content(page, content_selectors)

    if _ANTI_BOT_PATTERNS.search(final_url) or _ANTI_BOT_PATTERNS.search(
        (title or "") + body[:1500]
    ):
        raise ConfigurationError(
            "Zhihu (or site) blocked automated browser (security verification). "
            "Ensure system Chrome is used and cookies are fresh; see docs/COOKIES.md"
        )

    if _LOGIN_WALL_PATTERNS.search(body[:2000]) or (title and "进入知乎" in title):
        raise ConfigurationError(
            "Page shows login wall. Re-export cookies: "
            "python scripts/export_cookies.py zhihu"
        )

    if len(body.strip()) < min_body_chars:
        raise ConfigurationError(
            f"Extracted body too short ({len(body.strip())} chars). "
            "Cookies may be expired or the page layout changed."
        )

    author = _first_inner_text(page, author_selectors or [])
    avatar = _first_image_src(page, avatar_selectors or [])
    author_url = _first_href(page, author_url_selectors or [])

    return PageContent(
        url=page.url,
        title=title,
        body_text=body.strip(),
        author=author,
        author_avatar=avatar,
        author_url=author_url,
    )


def _create_context(
    browser: Any,
    cookie_data: dict[str, Any] | list[dict[str, Any]],
    seed_domain: str,
) -> Any:
    from on1y.browser.cookies import (
        is_cookie_list,
        is_storage_state,
        normalize_cookie_list,
        seed_url_for_domain,
    )

    context_opts: dict[str, Any] = {
        "locale": "zh-CN",
        "user_agent": DEFAULT_USER_AGENT,
        "viewport": {"width": 1280, "height": 900},
    }
    if is_storage_state(cookie_data):
        context_opts["storage_state"] = cookie_data
        return browser.new_context(**context_opts)

    if is_cookie_list(cookie_data):
        context = browser.new_context(**context_opts)
        cookies = normalize_cookie_list(cookie_data, seed_domain)
        seed = seed_url_for_domain(seed_domain)
        page = context.new_page()
        page.goto(seed, wait_until="domcontentloaded")
        context.add_cookies(cookies)
        page.close()
        return context

    raise ConfigurationError("Unsupported cookie payload")


def _wait_for_content(page: Any, selectors: list[str], *, require_selector: bool) -> None:
    """Soft-wait for any selector; optional strict mode raises on total failure."""
    last_error: Exception | None = None
    per_selector = 3000

    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=per_selector, state="attached")
            logger.debug("Matched selector: %s", selector)
            return
        except Exception as exc:
            last_error = exc
            logger.debug("Selector not ready: %s", selector)

    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        logger.debug("networkidle timeout, continuing with DOM extraction")

    if require_selector and last_error:
        raise last_error


def _trigger_lazy_render(page: Any) -> None:
    try:
        page.evaluate("window.scrollTo(0, Math.min(800, document.body.scrollHeight))")
        page.wait_for_timeout(800)
    except Exception:
        pass


def _first_inner_text(page: Any, selectors: list[str]) -> str | None:
    for selector in selectors:
        element = page.query_selector(selector)
        if element:
            text = (element.inner_text() or "").strip()
            if text:
                return text
    return None


def _first_image_src(page: Any, selectors: list[str]) -> str | None:
    for selector in selectors:
        element = page.query_selector(selector)
        if element:
            for attr in ("src", "data-src", "data-original", "data-actualsrc"):
                src = (element.get_attribute(attr) or "").strip()
                if src:
                    return src
            srcset = (element.get_attribute("srcset") or "").strip()
            if srcset:
                first = srcset.split(",")[0].strip().split(" ")[0]
                if first:
                    return first
    return None


def _first_href(page: Any, selectors: list[str]) -> str | None:
    for selector in selectors:
        element = page.query_selector(selector)
        if element:
            href = (element.get_attribute("href") or "").strip()
            if href:
                return href
    return None


def _extract_combined_content(page: Any, selectors: list[str]) -> str:
    chunks: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        for element in page.query_selector_all(selector):
            text = (element.inner_text() or "").strip()
            if not text or text in seen or len(text) < 8:
                continue
            seen.add(text)
            chunks.append(text)
        if chunks:
            break

    if not chunks:
        for selector in ["article", "main", '[role="main"]', ".App-main", "#root"]:
            element = page.query_selector(selector)
            if element:
                text = (element.inner_text() or "").strip()
                if len(text) > 50:
                    return text

    if not chunks:
        return (page.inner_text("body") or "").strip()

    return "\n\n".join(chunks)
