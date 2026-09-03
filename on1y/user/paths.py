"""Per-user data directories under data/users/<id>/."""

from __future__ import annotations

from pathlib import Path

from on1y import config
get_settings = config.get_settings  # compatibility alias for integrations/tests

COOKIE_PLATFORMS = ("youtube", "bilibili", "zhihu", "xiaohongshu", "twitter", "zlibrary")


def user_dir(user_id: int) -> Path:
    root = config.get_settings().data_dir / "users" / str(user_id)
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


def user_smtp_settings_path(user_id: int) -> Path:
    return user_dir(user_id) / "smtp_settings.json"


def user_economist_cache_dir(user_id: int) -> Path:
    path = user_dir(user_id) / "economist"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_books_cache_dir(user_id: int) -> Path:
    path = user_dir(user_id) / "books" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_books_cache_dir(user_id: int, override: str | None) -> Path:
    if override and str(override).strip():
        path = Path(str(override).strip()).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise PermissionError(f"无权写入目录 {path}") from exc
        except OSError as exc:
            raise OSError(f"无法创建目录 {path}: {exc}") from exc
        return path
    return user_books_cache_dir(user_id)


def user_feeds_path(user_id: int) -> Path:
    return user_dir(user_id) / "feeds.yaml"
