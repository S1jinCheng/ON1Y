"""Per-user data directories under data/users/<id>/."""

from __future__ import annotations

from pathlib import Path

from on1y.config import get_settings

COOKIE_PLATFORMS = ("youtube", "bilibili", "zhihu", "xiaohongshu", "twitter")


def user_dir(user_id: int) -> Path:
    root = get_settings().data_dir / "users" / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_cookies_dir(user_id: int) -> Path:
    path = user_dir(user_id) / "cookies"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_cookie_path(user_id: int, platform: str) -> Path:
    return user_cookies_dir(user_id) / f"{platform}.json"


def user_llm_settings_path(user_id: int) -> Path:
    return user_dir(user_id) / "llm_settings.json"


def user_economist_cache_dir(user_id: int) -> Path:
    path = user_dir(user_id) / "economist"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_feeds_path(user_id: int) -> Path:
    return user_dir(user_id) / "feeds.yaml"
