"""Book cover URL normalization and proxy allowlist."""

from __future__ import annotations

from urllib.parse import urlparse

_ALLOWED_SUFFIXES = (
    "doubanio.com",
    "douban.com",
    "googleusercontent.com",
    "books.google.com",
    "gstatic.com",
    "zlib.li",
    "z-lib.org",
    "z-lib.help",
    "z-library.sk",
    "z-lib.sk",
    "z-lib.fm",
    "z-lib.gd",
    "cdn-zlib.sk",
    "1lib.sk",
    "1lib.fr",
    "1lib.education",
    "singlelogin.me",
    "singlelogin.re",
    "annas-archive.org",
    "annas-archive.gl",
    "archive.org",
)


def normalize_cover_url(url: str | None) -> str | None:
    if not url:
        return None
    cleaned = str(url).strip()
    if not cleaned:
        return None
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    if cleaned.startswith("http://"):
        cleaned = "https://" + cleaned[len("http://") :]
    return cleaned


def cover_proxy_allowed(url: str) -> bool:
    try:
        parsed = urlparse(normalize_cover_url(url) or "")
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    try:
        import ipaddress

        if not ipaddress.ip_address(host).is_global:
            return False
    except ValueError:
        pass
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _ALLOWED_SUFFIXES)


def cover_fetch_headers(url: str) -> dict[str, str]:
    host = (urlparse(url).hostname or "").lower()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if "douban" in host:
        headers["Referer"] = "https://book.douban.com/"
    elif "cdn-zlib" in host:
        headers["Referer"] = "https://z-lib.sk/"
    elif any(
        token in host
        for token in ("z-lib", "zlib", "1lib", "singlelogin", "z-library")
    ):
        headers["Referer"] = f"https://{host}/"
    return headers
