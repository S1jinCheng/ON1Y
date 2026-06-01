"""Bilibili URL helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse, urlunparse

_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)
_B23_HOST = "b23.tv"


def bilibili_video_url(bvid: str, *, page: int | None = None) -> str:
    token = str(bvid or "").strip()
    if not token:
        raise ValueError("missing bvid")
    if not token.upper().startswith("BV"):
        token = f"BV{token}"
    token = "BV" + token[2:]
    base = f"https://www.bilibili.com/video/{token}"
    if page and page > 1:
        return f"{base}?p={page}"
    return base


def normalize_bilibili_url(url: str) -> str:
    """Canonicalize Bilibili video URLs for deduplication."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = parsed.path or ""

    match = _BVID_RE.search(path) or _BVID_RE.search(cleaned)
    if not match and host == _B23_HOST:
        return cleaned.rstrip("/")

    if not match:
        normalized = parsed._replace(fragment="")
        return urlunparse(normalized).geturl().rstrip("/")

    bvid = "BV" + match.group(1)[2:]
    page = 0
    query = parse_qs(parsed.query)
    if "p" in query and query["p"]:
        try:
            page = int(str(query["p"][0]))
        except ValueError:
            page = 0
    canonical = bilibili_video_url(bvid, page=page if page > 1 else None)
    return canonical.rstrip("/")


def is_bilibili_video_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    if _B23_HOST in host:
        return True
    if "bilibili.com" not in host:
        return False
    path = urlparse(url).path or ""
    return "/video/" in path or _BVID_RE.search(path) is not None
