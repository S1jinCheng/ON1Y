"""Resolve per-platform cookie paths from settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from on1y.browser.cookies import is_cookie_list, is_storage_state, load_cookie_file
from on1y.auth.context import get_current_user_id
from on1y.config import Settings, get_settings
from on1y.cookies.netscape import write_netscape_cookie_file
from on1y.exceptions import ConfigurationError
from on1y.user.paths import user_cookie_path

PLATFORM_COOKIE_ATTR = {
    "youtube": "youtube_cookies_path",
    "bilibili": "bilibili_cookies_path",
    "zhihu": "zhihu_cookies_path",
    "xiaohongshu": "xiaohongshu_cookies_path",
    "twitter": "twitter_cookies_path",
}


def resolve_cookie_path(
    platform: str,
    settings: Settings | None = None,
    *,
    user_id: int | None = None,
) -> Path:
    settings = settings or get_settings()
    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        raise ConfigurationError(f"user context required to resolve {platform} cookie path")
    per_user = user_cookie_path(uid, platform)
    if platform == "zlibrary":
        return per_user
    attr = PLATFORM_COOKIE_ATTR.get(platform)
    if not attr:
        raise ConfigurationError(f"No cookie path configured for platform: {platform}")
    if per_user.is_file():
        return per_user
    # Legacy data/cookies/*.json is only for migrated user id=1 — never share across users.
    if uid == 1:
        legacy = getattr(settings, attr)
        if legacy.is_file():
            return legacy
    return per_user


def cookie_file_status(platform: str, settings: Settings | None = None) -> dict[str, Any]:
    path = resolve_cookie_path(platform, settings)
    return {
        "platform": platform,
        "path": str(path),
        "exists": path.is_file(),
    }


def extract_cookie_list(cookie_data: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if is_storage_state(cookie_data):
        raw = cookie_data["cookies"]
        return [c for c in raw if isinstance(c, dict) and "name" in c and "value" in c]
    if is_cookie_list(cookie_data):
        return cookie_data
    raise ConfigurationError("Cookie payload has no cookies array")


def invalidate_cookie_sidecar(path: Path) -> None:
    """Remove yt-dlp Netscape sidecar so the next read regenerates from JSON."""
    netscape_path = path.with_suffix(path.suffix + ".netscape.txt")
    if netscape_path.is_file():
        netscape_path.unlink()


def load_cookies_for_ytdlp(path: Path, *, required: bool = True) -> Path | None:
    """
    Load JSON cookies and write a Netscape cookie file for yt-dlp.
    Returns path to Netscape file (alongside JSON, .netscape.txt suffix).
    """
    if not path.is_file():
        if required:
            raise ConfigurationError(
                f"Cookie file required but missing: {path}. "
                f"Run: python scripts/export_cookies.py <platform> — see docs/COOKIES.md"
            )
        return None
    data = load_cookie_file(path)
    cookies = extract_cookie_list(data)
    netscape_path = path.with_suffix(path.suffix + ".netscape.txt")
    write_netscape_cookie_file(cookies, netscape_path)
    return netscape_path
