"""Playwright helpers for X (Twitter) discovery and session verification."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

TWITTER_HOME_URL = "https://x.com/home"
TWITTER_BOOKMARKS_URL = "https://x.com/i/bookmarks"
TWITTER_SEED_DOMAIN = ".x.com"

_STATUS_ID_RE = re.compile(r"/status/(\d+)")
_LOGIN_WALL_RE = re.compile(
    r"Sign in to X|Log in to X|登录\s*X|Create your account|Don.?t miss what.?s happening",
    re.IGNORECASE,
)
_ANTIBOT_RE = re.compile(
    r"Something went wrong|Try again|Rate limit|over capacity|automated|unusual activity",
    re.IGNORECASE,
)

_COLLECT_STATUS_JS = """
() => {
  const rows = [];
  const seen = new Set();
  const articles = document.querySelectorAll('article[data-testid="tweet"]');
  for (const article of articles) {
    const social = article.querySelector('[data-testid="socialContext"]');
    const socialText = social ? (social.innerText || '') : '';
    const isRetweet = /reposted|retweeted|转推|转发了/i.test(socialText);
    let href = '';
    const timeLink = article.querySelector('a[href*="/status/"] time');
    if (timeLink && timeLink.parentElement) {
      href = timeLink.parentElement.getAttribute('href') || '';
    }
    if (!href) {
      const link = article.querySelector('a[href*="/status/"]');
      href = link ? (link.getAttribute('href') || '') : '';
    }
    const match = href.match(/\\/status\\/(\\d+)/);
    if (!match) continue;
    const statusId = match[1];
    if (seen.has(statusId)) continue;
    seen.add(statusId);
    let published = null;
    const timeEl = article.querySelector('time[datetime]');
    if (timeEl) {
      published = timeEl.getAttribute('datetime');
    }
    let preview = '';
    const textEl = article.querySelector('[data-testid="tweetText"]');
    if (textEl) {
      preview = (textEl.innerText || '').trim().slice(0, 280);
    }
    rows.push({ status_id: statusId, href, is_retweet: isRetweet, published, preview });
  }
  return rows;
}
"""


@dataclass(frozen=True)
class TwitterStatusRef:
    status_id: str
    url: str
    is_retweet: bool
    published: str | None = None
    preview: str | None = None


def parse_status_id(url: str) -> str | None:
    match = _STATUS_ID_RE.search(url)
    return match.group(1) if match else None


def normalize_twitter_status_url(url: str) -> str:
    """Canonical status URL for deduplication."""
    status_id = parse_status_id(url)
    if status_id:
        return f"https://x.com/i/web/status/{status_id}"
    parsed = urlparse(url.strip())
    return parsed._replace(fragment="").geturl().rstrip("/")


def is_twitter_login_wall(snippet: str) -> bool:
    return bool(_LOGIN_WALL_RE.search(snippet))


def is_twitter_host(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    return any(token in host for token in ("x.com", "twitter.com"))


def _href_to_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http"):
        return normalize_twitter_status_url(href)
    if href.startswith("/"):
        return normalize_twitter_status_url(f"https://x.com{href}")
    return normalize_twitter_status_url(href)


def _page_snippet(page: Any, limit: int = 2500) -> str:
    try:
        return (page.inner_text("body") or "")[:limit]
    except Exception:
        return ""


def check_twitter_page_health(page: Any) -> None:
    """Raise ConfigurationError on login wall or anti-bot pages."""
    final_url = page.url or ""
    snippet = _page_snippet(page)
    if "/login" in final_url or "/i/flow/login" in final_url:
        raise ConfigurationError(
            "X login wall. Re-export cookies from a logged-in x.com session."
        )
    if _LOGIN_WALL_RE.search(snippet):
        raise ConfigurationError(
            "X login wall. Re-export cookies: python scripts/export_cookies.py twitter"
        )
    if _ANTIBOT_RE.search(snippet) or _ANTIBOT_RE.search(final_url):
        raise ConfigurationError(
            "X blocked automated access (rate limit or verification). "
            "Wait a few minutes and ensure cookies are fresh."
        )


def twitter_likes_url(handle: str) -> str:
    token = (handle or "").strip().removeprefix("@")
    if not token:
        raise ValueError("empty X handle")
    return f"https://x.com/{token}/likes"


def resolve_twitter_account_handle(
    cookie_path: Path,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Read the logged-in account handle from the home page profile link."""
    from on1y.browser.playwright_isolated import run_playwright_isolated

    settings = settings or get_settings()

    def _run() -> str | None:
        from on1y.browser.playwright_session import PlaywrightSession

        with PlaywrightSession(cookie_path=cookie_path, seed_domain=TWITTER_SEED_DOMAIN) as session:
            page = session.new_page()
            try:
                page.goto(TWITTER_HOME_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(max(settings.playwright_settle_ms, 2500))
                check_twitter_page_health(page)
                return _account_handle_from_page(page)
            finally:
                page.close()

    return run_playwright_isolated(_run)


_TWITTER_ACCOUNT_META_JS = """
() => {
  const normSrc = (img) => {
    if (!img) return null;
    let src = img.getAttribute('src') || '';
    if (!src) return null;
    if (src.startsWith('//')) src = 'https:' + src;
    return src;
  };
  let handle = null;
  let name = null;
  let avatar = null;
  const profileLink = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]');
  if (profileLink) {
    const href = (profileLink.getAttribute('href') || '').split('?')[0];
    if (href.startsWith('/')) {
      handle = href.split('/').filter(Boolean)[0] || null;
    }
    avatar = normSrc(profileLink.querySelector('img[src*="profile_images"], img')) || avatar;
  }
  const switcher = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]');
  if (switcher) {
    avatar =
      normSrc(switcher.querySelector('img[src*="profile_images"], img')) || avatar;
    const lines = (switcher.innerText || '')
      .split('\\n')
      .map((s) => s.trim())
      .filter(Boolean);
    for (const line of lines) {
      if (line.startsWith('@')) handle = handle || line.slice(1);
      else if (!name) name = line;
    }
  }
  const navRoots = [
    document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]'),
    document.querySelector('a[data-testid="AppTabBar_Profile_Link"]'),
    document.querySelector('header'),
    document.querySelector('nav[role="navigation"]'),
  ].filter(Boolean);
  if (!avatar) {
    for (const root of navRoots) {
      const src = normSrc(root.querySelector('img[src*="profile_images"]'));
      if (src) {
        avatar = src;
        break;
      }
    }
  }
  return { handle, name, avatar };
}
"""


def _normalize_twitter_image_url(url: str | None) -> str | None:
    text = (url or "").strip()
    if not text:
        return None
    if text.startswith("//"):
        return f"https:{text}"
    return text


def _account_meta_from_page(page: Any) -> dict[str, str | None]:
    try:
        raw = page.evaluate(_TWITTER_ACCOUNT_META_JS)
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        return {"handle": None, "name": None, "avatar": None}
    return {
        "handle": str(raw.get("handle") or "").strip() or None,
        "name": str(raw.get("name") or "").strip() or None,
        "avatar": _normalize_twitter_image_url(str(raw.get("avatar") or "").strip() or None),
    }


def _account_handle_from_page(page: Any) -> str | None:
    return _account_meta_from_page(page).get("handle")


def _avatar_from_profile_page(page: Any, handle: str, *, settings: Settings) -> str | None:
    profile_url = f"https://x.com/{handle.strip().removeprefix('@')}"
    page.goto(profile_url, wait_until="domcontentloaded")
    page.wait_for_timeout(max(settings.playwright_settle_ms, 2000))
    check_twitter_page_health(page)
    try:
        src = page.evaluate(
            """
            () => {
              const img =
                document.querySelector('[data-testid="UserAvatar-Container-Unknown"] img') ||
                document.querySelector('[data-testid="UserAvatar-Container"] img') ||
                document.querySelector('a[href*="/photo"] img[src*="profile_images"]') ||
                document.querySelector('img[src*="profile_images"]');
              if (!img) return null;
              let src = img.getAttribute('src') || '';
              if (src.startsWith('//')) src = 'https:' + src;
              return src || null;
            }
            """
        )
    except Exception:
        return None
    return _normalize_twitter_image_url(str(src or "").strip() or None)


def verify_twitter_session(
    cookie_path: Path,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Probe saved cookies by opening the home timeline."""
    from on1y.browser.playwright_isolated import run_playwright_isolated

    settings = settings or get_settings()

    def _run() -> dict[str, Any]:
        from on1y.browser.playwright_session import PlaywrightSession

        with PlaywrightSession(cookie_path=cookie_path, seed_domain=TWITTER_SEED_DOMAIN) as session:
            page = session.new_page()
            try:
                page.goto(TWITTER_HOME_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(max(settings.playwright_settle_ms, 2500))
                check_twitter_page_health(page)

                meta = _account_meta_from_page(page)
                account_id = meta.get("handle")
                account_name = meta.get("name")
                avatar_url = meta.get("avatar")

                if account_id and not avatar_url:
                    avatar_url = _avatar_from_profile_page(page, account_id, settings=settings)

                if account_id and not account_name:
                    account_name = f"@{account_id}"

                articles = page.query_selector_all('article[data-testid="tweet"]')
                detail = f"已登录 · 首页可见 {len(articles)} 条推文" if articles else "已登录"
                if account_name:
                    detail = f"{account_name} · {detail}"

                return {
                    "valid": True,
                    "account_id": account_id,
                    "account_name": account_name or account_id,
                    "avatar_url": avatar_url,
                    "detail": detail,
                    "verified_at": None,
                }
            finally:
                page.close()

    return run_playwright_isolated(_run)


_TWITTER_AUTHOR_META_JS = """
() => {
  const article = document.querySelector('article[data-testid="tweet"]');
  if (!article) return null;
  let author = null;
  let author_url = null;
  let author_avatar = null;
  const nameRoot = article.querySelector('[data-testid="User-Name"]');
  if (nameRoot) {
    const lines = (nameRoot.innerText || '').split('\\n').map((s) => s.trim()).filter(Boolean);
    author = lines.find((l) => !l.startsWith('@')) || lines[0] || null;
    const link = nameRoot.querySelector('a[href^="/"]');
    if (link) {
      const href = (link.getAttribute('href') || '').split('?')[0];
      if (href.startsWith('/')) author_url = 'https://x.com' + href;
    }
  }
  const img =
    article.querySelector('[data-testid="Tweet-User-Avatar"] img') ||
    article.querySelector('img[src*="profile_images"]');
  if (img) {
    author_avatar = img.getAttribute('src') || null;
    if (author_avatar && author_avatar.startsWith('//')) {
      author_avatar = 'https:' + author_avatar;
    }
  }
  return { author, author_url, author_avatar };
}
"""


def extract_twitter_author_meta(page: Any) -> dict[str, str | None]:
    try:
        raw = page.evaluate(_TWITTER_AUTHOR_META_JS)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        "author": str(raw.get("author") or "").strip() or None,
        "author_url": str(raw.get("author_url") or "").strip() or None,
        "author_avatar": str(raw.get("author_avatar") or "").strip() or None,
    }


def discover_twitter_status_refs(
    cookie_path: Path,
    *,
    start_url: str,
    max_items: int,
    max_scrolls: int,
    exclude_retweets: bool = True,
    settings: Settings | None = None,
) -> list[TwitterStatusRef]:
    """Open a timeline page and collect status links from the DOM."""
    from on1y.browser.playwright_isolated import run_playwright_isolated

    settings = settings or get_settings()
    cap = max(1, min(max_items, 200))
    scrolls = max(0, min(max_scrolls, 20))

    def _run() -> list[TwitterStatusRef]:
        from on1y.browser.playwright_session import PlaywrightSession

        collected: list[TwitterStatusRef] = []
        seen: set[str] = set()

        with PlaywrightSession(cookie_path=cookie_path, seed_domain=TWITTER_SEED_DOMAIN) as session:
            page = session.new_page()
            try:
                page.goto(start_url, wait_until="domcontentloaded")
                page.wait_for_timeout(max(settings.playwright_settle_ms, 2500))
                check_twitter_page_health(page)

                for round_idx in range(scrolls + 1):
                    raw_rows: list[dict[str, Any]] = page.evaluate(_COLLECT_STATUS_JS)
                    for row in raw_rows:
                        status_id = str(row.get("status_id") or "").strip()
                        if not status_id or status_id in seen:
                            continue
                        is_retweet = bool(row.get("is_retweet"))
                        if exclude_retweets and is_retweet:
                            continue
                        seen.add(status_id)
                        url = _href_to_url(str(row.get("href") or "")) or normalize_twitter_status_url(
                            f"https://x.com/i/web/status/{status_id}"
                        )
                        collected.append(
                            TwitterStatusRef(
                                status_id=status_id,
                                url=url,
                                is_retweet=is_retweet,
                                published=str(row.get("published") or "").strip() or None,
                                preview=str(row.get("preview") or "").strip() or None,
                            )
                        )
                        if len(collected) >= cap:
                            return collected
                    if round_idx >= scrolls:
                        break
                    page.evaluate("window.scrollBy(0, Math.max(window.innerHeight * 0.85, 600))")
                    page.wait_for_timeout(1400)
            finally:
                page.close()
        return collected

    return run_playwright_isolated(_run)
