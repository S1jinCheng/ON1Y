"""Fetch Zhihu followees via logged-in cookies (mirrors sync_youtube_feeds pattern)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from on1y.config import Settings, get_settings
from on1y.cookies.loader import extract_cookie_list, load_cookie_file, resolve_cookie_path
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

ZHIHU_API = "https://www.zhihu.com/api/v4"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.zhihu.com/",
}


def _cookie_jar(cookie_path: Path) -> dict[str, str]:
    data = load_cookie_file(cookie_path)
    cookies = extract_cookie_list(data)
    return {
        str(c["name"]): str(c["value"])
        for c in cookies
        if "zhihu.com" in str(c.get("domain", ""))
    }


def fetch_zhihu_me(*, cookie_path: Path | None = None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("zhihu", settings)
    jar = _cookie_jar(path)
    if not jar:
        raise ConfigurationError(f"No zhihu.com cookies in {path}")

    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        response = client.get(f"{ZHIHU_API}/me")
        response.raise_for_status()
        payload = response.json()
        if not payload.get("url_token"):
            raise ConfigurationError("Zhihu /me did not return url_token — cookies may be expired")
        return payload


def fetch_zhihu_followees(
    *,
    cookie_path: Path | None = None,
    settings: Settings | None = None,
    page_size: int = 20,
    max_users: int = 500,
) -> list[dict[str, str]]:
    """
    Return followees as {url_token, name, feed_type} dicts.
    Uses the logged-in account from zhihu cookies.
    """
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("zhihu", settings)
    me = fetch_zhihu_me(cookie_path=path, settings=settings)
    member_token = str(me["url_token"])
    feed_type = settings.zhihu_follow_feed_type.strip().lower() or "activities"
    jar = _cookie_jar(path)

    rows: list[dict[str, str]] = []
    offset = 0

    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        while len(rows) < max_users:
            response = client.get(
                f"{ZHIHU_API}/members/{member_token}/followees",
                params={"offset": offset, "limit": page_size},
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("data") or []
            if not batch:
                break
            for user in batch:
                token = user.get("url_token")
                if not token:
                    continue
                rows.append(
                    {
                        "url_token": str(token),
                        "name": str(user.get("name") or token),
                        "feed_type": feed_type,
                    }
                )
                if len(rows) >= max_users:
                    break
            paging = payload.get("paging") or {}
            if paging.get("is_end"):
                break
            offset += page_size

    logger.info("Fetched %s Zhihu followee(s) for %s", len(rows), me.get("name"))
    return rows


def fetch_zhihu_favlists(
    *,
    cookie_path: Path | None = None,
    settings: Settings | None = None,
    page_size: int = 20,
    max_lists: int = 200,
) -> list[dict[str, str]]:
    """
    Return the logged-in user's 收藏夹 as {id, name, feed_type=collection} dicts.
    """
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("zhihu", settings)
    me = fetch_zhihu_me(cookie_path=path, settings=settings)
    member_token = str(me["url_token"])
    jar = _cookie_jar(path)

    rows: list[dict[str, str]] = []
    offset = 0

    with httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds) as client:
        while len(rows) < max_lists:
            response = client.get(
                f"{ZHIHU_API}/members/{member_token}/favlists",
                params={"offset": offset, "limit": page_size},
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("data") or []
            if not batch:
                break
            for favlist in batch:
                fav_id = favlist.get("id")
                if fav_id is None:
                    continue
                rows.append(
                    {
                        "id": str(fav_id),
                        "name": str(favlist.get("title") or fav_id),
                        "feed_type": "collection",
                    }
                )
                if len(rows) >= max_lists:
                    break
            paging = payload.get("paging") or {}
            if paging.get("is_end"):
                break
            offset += page_size

    logger.info("Fetched %s Zhihu favlist(s) for %s", len(rows), me.get("name"))
    return rows


def _follow_entry_key(entry: dict[str, str]) -> tuple[str, str]:
    feed_type = (entry.get("feed_type") or "activities").strip().lower()
    item_id = str(entry.get("url_token") or entry.get("id") or "").strip()
    return feed_type, item_id


def merge_follows_file(
    followees: list[dict[str, str]],
    follows_path: Path,
    *,
    feed_type: str | None = None,
) -> tuple[int, int]:
    """
    Merge subscription entries into config/zhihu_follows.txt.
    Each entry needs feed_type + url_token (users/columns) or id (collections).
    Returns (added, total).
    """
    existing: set[tuple[str, str]] = set()
    lines: list[str] = []

    if follows_path.is_file():
        from on1y.ingestion.zhihu_feeds import parse_follow_line

        for line in follows_path.read_text(encoding="utf-8").splitlines():
            lines.append(line)
            parsed = parse_follow_line(line)
            if parsed:
                existing.add(parsed)

    added = 0
    for entry in followees:
        ftype, item_id = _follow_entry_key(entry)
        if feed_type:
            ftype = feed_type.strip().lower()
        if not item_id:
            continue
        key = (ftype, item_id)
        if key in existing:
            continue
        lines.append(f"{ftype}:{item_id}")
        existing.add(key)
        added += 1

    follows_path.parent.mkdir(parents=True, exist_ok=True)
    follows_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return added, len(existing)
