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
  if (!handle) {
    for (const a of document.querySelectorAll('a[href^="/"]')) {
      const href = (a.getAttribute('href') || '').split('?')[0];
      const parts = href.split('/').filter(Boolean);
      if (parts.length !== 1) continue;
      const token = parts[0];
      const reserved = new Set([
        'home', 'explore', 'search', 'notifications', 'messages', 'i', 'settings',
        'compose', 'login', 'signup', 'intent',
      ]);
      if (reserved.has(token.toLowerCase())) continue;
      const label = (a.getAttribute('aria-label') || a.getAttribute('title') || '').toLowerCase();
      if (
        label.includes('profile') ||
        label.includes('account') ||
        label.includes('个人资料') ||
        label.includes('账号') ||
        label.includes('帐户')
      ) {
        handle = token;
        break;
      }
    }
  }
  return { handle, name, avatar };
}
"""


_TWITTER_ACCOUNT_FALLBACK_META_JS = """
() => {
  const normSrc = (img) => {
    if (!img) return null;
    let src = img.getAttribute('src') || '';
    if (!src) return null;
    if (src.startsWith('//')) src = 'https:' + src;
    return src;
  };
  const reserved = new Set([
    'home', 'explore', 'search', 'notifications', 'messages', 'i', 'settings',
    'compose', 'login', 'signup', 'intent', 'bookmarks', 'lists', 'communities',
  ]);
  const handleFromHref = (href) => {
    const parts = (href || '').split('?')[0].split('/').filter(Boolean);
    if (parts.length !== 1 || reserved.has(parts[0].toLowerCase())) return null;
    return parts[0];
  };
  const roots = [
    document.querySelector('[role="navigation"]'),
    document.querySelector('nav'),
    document.querySelector('header'),
  ].filter(Boolean);
  let handle = null;
  let name = null;
  let avatar = null;
  const accountSelector = [
    '[data-testid="SideNav_AccountSwitcher_Button"]',
    '[data-testid*="AccountSwitcher"]',
    'button[aria-label*="Account"]',
    'button[aria-label*="账号"]',
    'button[aria-label*="帐户"]',
    '[role="button"][aria-label*="Account"]',
  ].join(',');
  const switcher = document.querySelector(accountSelector);
  if (switcher) {
    avatar = normSrc(switcher.querySelector('img[src*="profile_images"], img'));
    const lines = (switcher.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean);
    for (const line of lines) {
      if (line.startsWith('@')) handle = handle || line.slice(1);
      else if (!name && !/^(account|账号|帐户|profile|个人资料)$/i.test(line)) name = line;
    }
  }
  for (const root of roots) {
    if (!avatar) avatar = normSrc(root.querySelector('img[src*="profile_images"], img'));
    if (!handle) {
      const links = [...root.querySelectorAll('a[href^="/"]')];
      for (const link of links) {
        const label = (link.getAttribute('aria-label') || link.getAttribute('title') || '').toLowerCase();
        const candidate = handleFromHref(link.getAttribute('href'));
        if (candidate && (
          label.includes('profile') || label.includes('account') ||
          label.includes('个人资料') || label.includes('账号') || label.includes('帐户')
        )) {
          handle = candidate;
          break;
        }
      }
    }
  }
  return { handle, name, avatar };
}
"""


_TWITTER_ACCOUNT_SETTINGS_META_JS = """
() => {
  const valueOf = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      const value = node && ('value' in node ? node.value : node.getAttribute('content'));
      if (value && String(value).trim()) return String(value).trim();
    }
    return null;
  };
  const image = document.querySelector('img[src*="profile_images"]');
  return {
    handle: valueOf([
      'input[name="username"]',
      'input[autocomplete="username"]',
      'input[aria-label*="Username"]',
      'input[aria-label*="用户名"]',
    ]),
    name: valueOf([
      'input[name="displayName"]',
      'input[name="display_name"]',
      'input[aria-label*="Name"]',
      'input[aria-label*="名称"]',
    ]),
    avatar: image ? image.getAttribute('src') : null,
  };
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


def _account_meta_from_fallback_page(page: Any) -> dict[str, str | None]:
    try:
        raw = page.evaluate(_TWITTER_ACCOUNT_FALLBACK_META_JS)
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        return {"handle": None, "name": None, "avatar": None}
    return {
        "handle": str(raw.get("handle") or "").strip() or None,
        "name": str(raw.get("name") or "").strip() or None,
        "avatar": _normalize_twitter_image_url(str(raw.get("avatar") or "").strip() or None),
    }


def _account_meta_from_settings_page(page: Any, *, settings: Settings) -> dict[str, str | None]:
    try:
        page.goto("https://x.com/settings/profile", wait_until="domcontentloaded")
        page.wait_for_timeout(max(settings.playwright_settle_ms, 2000))
        check_twitter_page_health(page)
        raw = page.evaluate(_TWITTER_ACCOUNT_SETTINGS_META_JS)
    except Exception:
        return {"handle": None, "name": None, "avatar": None}
    if not isinstance(raw, dict):
        return {"handle": None, "name": None, "avatar": None}
    handle = str(raw.get("handle") or "").strip().removeprefix("@") or None
    return {
        "handle": handle,
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
                if not all(meta.values()):
                    fallback = _account_meta_from_fallback_page(page)
                    for key in ("handle", "name", "avatar"):
                        if not meta.get(key) and fallback.get(key):
                            meta[key] = fallback[key]
                if not all(meta.values()):
                    settings_meta = _account_meta_from_settings_page(page, settings=settings)
                    for key in ("handle", "name", "avatar"):
                        if not meta.get(key) and settings_meta.get(key):
                            meta[key] = settings_meta[key]
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


_CLICK_FOLLOWING_TAB_JS = """
() => {
  const followingRe = /^(Following|正在关注|订阅|关注)$/i;
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  let followingTab = null;
  for (const tab of tabs) {
    const text = (tab.innerText || '').trim().split('\\n')[0].trim();
    if (followingRe.test(text)) {
      followingTab = tab;
      break;
    }
  }
  if (!followingTab) {
    return { found: false, active: false, clicked: false };
  }
  const wasActive = followingTab.getAttribute('aria-selected') === 'true';
  if (!wasActive) {
    followingTab.click();
  }
  const active = followingTab.getAttribute('aria-selected') === 'true';
  return { found: true, active, clicked: !wasActive };
}
"""

_ACTIVE_HOME_TAB_JS = """
() => {
  const followingRe = /^(Following|正在关注|订阅|关注)$/i;
  const forYouRe = /^(For you|For You|为你推荐|推荐)$/i;
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  for (const tab of tabs) {
    if (tab.getAttribute('aria-selected') !== 'true') continue;
    const text = (tab.innerText || '').trim().split('\\n')[0].trim();
    if (followingRe.test(text)) return 'following';
    if (forYouRe.test(text)) return 'for_you';
    return text || 'unknown';
  }
  return 'unknown';
}
"""


def active_twitter_home_tab(page: Any) -> str:
    try:
        return str(page.evaluate(_ACTIVE_HOME_TAB_JS) or "unknown").strip() or "unknown"
    except Exception:
        return "unknown"


def click_twitter_following_tab(page: Any) -> bool:
    """Switch home timeline from For You to Following when the tab is present."""
    try:
        raw = page.evaluate(_CLICK_FOLLOWING_TAB_JS)
    except Exception:
        return False
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("found"))


def ensure_twitter_following_tab(page: Any, *, settings: Settings) -> None:
    """Require the Following tab before scraping home — never ingest For You."""
    settle = max(settings.playwright_settle_ms, 2000)
    last_active = "unknown"
    for attempt in range(3):
        click_twitter_following_tab(page)
        page.wait_for_timeout(900 if attempt else settle)
        last_active = active_twitter_home_tab(page)
        if last_active == "following":
            return
        if attempt < 2:
            page.wait_for_timeout(settle)
    raise ConfigurationError(
        "X home timeline is not on the Following tab "
        f"(active={last_active!r}); refusing to ingest For You recommendations"
    )


_EXTRACT_STATUS_JS = """
(statusId) => {
  const normUrl = (href) => {
    if (!href) return '';
    if (href.startsWith('/')) return 'https://x.com' + href.split('?')[0];
    return href.split('?')[0];
  };

  const isInside = (node, ancestor) => {
    if (!node || !ancestor) return false;
    let cur = node;
    while (cur) {
      if (cur === ancestor) return true;
      cur = cur.parentElement;
    }
    return false;
  };

  const parseUser = (root) => {
    const block = root.querySelector('[data-testid="User-Name"]');
    if (!block) return { author: '', handle: '' };
    const lines = (block.innerText || '').split('\\n').map((s) => s.trim()).filter(Boolean);
    const handleLine = lines.find((l) => l.startsWith('@')) || '';
    const handle = handleLine.replace(/^@/, '');
    const author = lines[0] || '';
    return { author, handle };
  };

  const parseMetric = (label) => {
    const match = String(label || '').replace(/,/g, '').match(/(\d+(?:\.\d+)?)\s*([KMB万亿])?/i);
    if (!match) return null;
    const number = Number(match[1]);
    const suffix = String(match[2] || '').toLowerCase();
    const multiplier = suffix === 'k' ? 1e3
      : suffix === 'm' ? 1e6
      : suffix === 'b' ? 1e9
      : suffix === '万' ? 1e4
      : suffix === '亿' ? 1e8
      : 1;
    return Number.isFinite(number) ? Math.round(number * multiplier) : null;
  };

  const socialStats = (root) => {
    const find = (testid) => {
      const el = root.querySelector('[data-testid="' + testid + '"]');
      if (!el) return null;
      return parseMetric(el.getAttribute('aria-label') || el.innerText || '');
    };
    const result = {};
    const likes = find('like');
    const replies = find('reply');
    if (likes !== null) result.like_count = likes;
    if (replies !== null) result.comment_count = replies;
    return result;
  };

  const statusLink = (root) => {
    const timeParent = root.querySelector('a[href*="/status/"] time');
    const link = timeParent && timeParent.parentElement
      ? timeParent.parentElement
      : root.querySelector('a[href*="/status/"]');
    return link ? normUrl(link.getAttribute('href') || '') : '';
  };

  const tweetText = (root, exclude) => {
    const parts = [];
    for (const el of root.querySelectorAll('[data-testid="tweetText"]')) {
      if (exclude && isInside(el, exclude)) continue;
      const t = (el.innerText || '').trim();
      if (t) parts.push(t);
    }
    return parts.join('\\n\\n');
  };

  const tweetTextOnly = (root) => {
    const parts = [];
    for (const el of root.querySelectorAll('[data-testid="tweetText"]')) {
      const t = (el.innerText || '').trim();
      if (t) parts.push(t);
    }
    return parts.join('\\n\\n');
  };

  const collectImages = (root, exclude) => {
    const images = [];
    const seen = new Set();
    for (const img of root.querySelectorAll('[data-testid="tweetPhoto"] img')) {
      if (exclude && isInside(img, exclude)) continue;
      let src = img.getAttribute('src') || '';
      if (!src || !src.includes('pbs.twimg.com')) continue;
      if (src.startsWith('//')) src = 'https:' + src;
      const url = src.split('?')[0] + '?format=jpg&name=large';
      if (seen.has(url)) continue;
      seen.add(url);
      images.push({ type: 'image', url });
    }
    return images;
  };

  const videoCaption = (comp) => {
    const parts = [];
    const video = comp.querySelector('video');
    if (video) {
      const aria = (video.getAttribute('aria-label') || '').trim();
      if (aria) parts.push(aria);
    }
    for (const sel of [
      '[data-testid="videoDescription"]',
      '[data-testid="altText"]',
      '[data-testid="transcriptText"]',
      '[data-testid="closedCaptions"]',
    ]) {
      for (const el of comp.querySelectorAll(sel)) {
        const t = (el.innerText || '').trim();
        if (t) parts.push(t);
      }
    }
    return Array.from(new Set(parts)).join('\\n').trim();
  };

  const collectVideos = (root, exclude) => {
    const videos = [];
    const seen = new Set();
    for (const comp of root.querySelectorAll('[data-testid="videoComponent"]')) {
      if (exclude && isInside(comp, exclude)) continue;
      let url = '';
      for (const a of comp.querySelectorAll('a[href*="/status/"]')) {
        const href = normUrl(a.getAttribute('href') || '');
        if (href && (href.includes('/video/') || /\\/status\\/\\d+\\/video/.test(href))) {
          url = href;
          break;
        }
      }
      if (!url) {
        const a = comp.querySelector('a[href*="/video/"]');
        if (a) url = normUrl(a.getAttribute('href') || '');
      }
      const caption = videoCaption(comp);
      const key = (url || '') + '|' + caption;
      if (seen.has(key)) continue;
      seen.add(key);
      videos.push({ type: 'video', url: url || null, caption: caption || null });
    }
    return videos;
  };

  const buildBlock = (root, exclude) => {
    const user = parseUser(root);
    return {
      author: user.author,
      handle: user.handle,
      text: exclude ? tweetText(root, exclude) : tweetTextOnly(root),
      url: statusLink(root),
      images: collectImages(root, exclude),
      videos: collectVideos(root, exclude),
    };
  };

  const parseReposter = (socialText) => {
    const text = (socialText || '').trim();
    if (!text) return '';
    const patterns = [
      /^(.+?)\\s+reposted$/i,
      /^(.+?)\\s+retweeted$/i,
      /^(.+?)\\s+转推了?$/,
      /^(.+?)\\s+转发了$/,
    ];
    for (const re of patterns) {
      const m = text.match(re);
      if (m) return m[1].trim();
    }
    return text;
  };

  const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
  let article = null;
  for (const candidate of articles) {
    for (const aLink of candidate.querySelectorAll('a[href*="/status/"]')) {
      const href = aLink.getAttribute('href') || '';
      if (statusId && href.includes('/status/' + statusId)) {
        article = candidate;
        break;
      }
    }
    if (article) break;
  }
  if (!article && articles.length) article = articles[0];
  if (!article) {
    const bodyText = (document.body.innerText || '').slice(0, 500);
    if (/unavailable|不存在|已被删除|account is suspended/i.test(bodyText)) {
      return { kind: 'unavailable', main: { text: '', images: [], videos: [] }, embedded: null };
    }
    return null;
  }

  const social = article.querySelector('[data-testid="socialContext"]');
  const socialText = social ? (social.innerText || '').trim() : '';
  const isRetweet = /reposted|retweeted|转推|转发了/i.test(socialText);
  const timeEl = article.querySelector('time[datetime]');

  const card = article.querySelector('[data-testid="card.wrapper"]');
  const postUrl = statusLink(article);

  let kind = 'tweet';
  let main = null;
  let embedded = null;

  if (card) {
    kind = 'quote';
    main = buildBlock(article, card);
    embedded = buildBlock(card, null);
  } else if (isRetweet) {
    kind = 'retweet';
    const body = buildBlock(article, null);
    main = {
      reposter: parseReposter(socialText),
      author: '',
      handle: '',
      text: '',
      url: postUrl,
      images: [],
      videos: [],
    };
    embedded = body;
  } else {
    main = buildBlock(article, null);
  }

  return {
    kind,
    author: main.author,
    handle: main.handle,
    text: main.text,
    url: postUrl,
    social_context: socialText || null,
    quoted: embedded,
    main,
    embedded,
    is_retweet: isRetweet,
    published: timeEl ? timeEl.getAttribute('datetime') : null,
    social_stats: socialStats(article),
  };
}
"""


@dataclass(frozen=True)
class TwitterStatusExtract:
    body_text: str
    raw_title: str | None
    author: str | None
    author_avatar: str | None
    author_url: str | None
    kind: str
    status_url: str | None
    published: str | None = None
    social_stats: dict[str, int] | None = None


def _extract_status_payload(page: Any, url: str) -> dict[str, Any]:
    from on1y.extract.twitter_body import payload_has_content

    status_id = parse_status_id(url) or ""
    raw = page.evaluate(_EXTRACT_STATUS_JS, status_id)
    if not isinstance(raw, dict):
        page.wait_for_timeout(2500)
        try:
            page.wait_for_selector('article[data-testid="tweet"]', timeout=8000)
        except Exception:
            pass
        raw = page.evaluate(_EXTRACT_STATUS_JS, status_id)
    if not isinstance(raw, dict):
        raise ConfigurationError("Could not locate tweet content on X status page")
    if str(raw.get("kind") or "") == "unavailable":
        raise ConfigurationError("Tweet unavailable or deleted on X")
    if not payload_has_content(raw):
        raise ConfigurationError("Tweet has no extractable text or media on X status page")
    return raw


def extract_twitter_status_from_page(page: Any, url: str) -> TwitterStatusExtract:
    """Parse the focal status on the current page into Markdown."""
    from on1y.extract.twitter_body import format_twitter_status_markdown, twitter_title_from_payload

    check_twitter_page_health(page)
    payload = _extract_status_payload(page, url)
    body = format_twitter_status_markdown(payload)
    if len(body.strip()) < 1:
        raise ConfigurationError("Tweet body empty after structured extraction")

    meta = extract_twitter_author_meta(page)
    main = payload.get("main") if isinstance(payload.get("main"), dict) else {}
    embedded = payload.get("embedded") if isinstance(payload.get("embedded"), dict) else {}
    kind = str(payload.get("kind") or "tweet")
    author = (
        str(main.get("author") or payload.get("author") or meta.get("author") or "").strip()
        or None
    )
    handle = str(main.get("handle") or payload.get("handle") or "").strip().removeprefix("@")
    if kind == "retweet" and embedded:
        author = str(embedded.get("author") or "").strip() or author
        handle = str(embedded.get("handle") or "").strip().removeprefix("@") or handle
    author_url = meta.get("author_url")
    if handle and not author_url:
        author_url = f"https://x.com/{handle}"
    from on1y.knowledge.creators import normalize_twitter_author_url

    author_url = normalize_twitter_author_url(author_url) or None

    return TwitterStatusExtract(
        body_text=body,
        raw_title=twitter_title_from_payload(payload),
        author=author,
        author_avatar=meta.get("author_avatar"),
        author_url=author_url,
        kind=str(payload.get("kind") or "tweet"),
        status_url=str(payload.get("url") or "").strip() or None,
        published=str(payload.get("published") or "").strip() or None,
        social_stats=payload.get("social_stats")
        if isinstance(payload.get("social_stats"), dict)
        else None,
    )


def fetch_twitter_status_markdown(
    url: str,
    *,
    cookie_path: Path,
    seed_domain: str = TWITTER_SEED_DOMAIN,
    settle_ms: int | None = None,
    session: Any | None = None,
    settings: Settings | None = None,
) -> TwitterStatusExtract:
    """Navigate to a status URL and extract Markdown (reuses session when provided)."""
    settings = settings or get_settings()
    settle = settle_ms if settle_ms is not None else settings.playwright_settle_ms
    normalized = normalize_twitter_status_url(url)

    def _on_page(page: Any) -> TwitterStatusExtract:
        page.goto(normalized, wait_until="domcontentloaded", timeout=settings.playwright_timeout_ms)
        page.wait_for_timeout(max(settle, 2500))
        return extract_twitter_status_from_page(page, normalized)

    if session is not None:
        page = session.new_page()
        try:
            return _on_page(page)
        finally:
            page.close()

    from on1y.browser.playwright_isolated import run_playwright_isolated
    from on1y.browser.playwright_session import PlaywrightSession

    def _run() -> TwitterStatusExtract:
        with PlaywrightSession(cookie_path=cookie_path, seed_domain=seed_domain) as sess:
            return fetch_twitter_status_markdown(
                normalized,
                cookie_path=cookie_path,
                seed_domain=seed_domain,
                settle_ms=settle,
                session=sess,
                settings=settings,
            )

    return run_playwright_isolated(_run)


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
    following_tab: bool = False,
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
                if following_tab and start_url.rstrip("/").endswith("/home"):
                    ensure_twitter_following_tab(page, settings=settings)

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
