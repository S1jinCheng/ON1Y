"""Load Z-Library remix session from per-user cookie file."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from on1y.books.builtin_sources import ZLIB_BASE
from on1y.books.settings_store import load_book_settings
from on1y.browser.cookies import load_cookie_file
from on1y.config import get_settings
from on1y.cookies.loader import extract_cookie_list, resolve_cookie_path


@dataclass(frozen=True)
class ZlibSession:
    host: str
    remix_userid: str
    remix_userkey: str


def _cookie_value(cookies: list[dict], *names: str) -> str | None:
    lowered = {n.lower() for n in names}
    for row in cookies:
        name = str(row.get("name") or "")
        if name.lower() in lowered:
            value = str(row.get("value") or "").strip()
            if value:
                return value
    return None


def load_zlib_session(user_id: int) -> ZlibSession | None:
    settings = get_settings()
    path = resolve_cookie_path("zlibrary", settings, user_id=user_id)
    if not path.is_file():
        return None
    try:
        data = load_cookie_file(path)
        cookies = extract_cookie_list(data)
    except Exception:
        return None
    remix_userid = _cookie_value(cookies, "remix_userid", "remix_userId")
    remix_userkey = _cookie_value(cookies, "remix_userkey")
    if not remix_userid or not remix_userkey:
        return None
    book_settings = load_book_settings(user_id)
    base = (book_settings.zlib_base_url or ZLIB_BASE).strip() or ZLIB_BASE
    host = urlparse(base).netloc or urlparse(ZLIB_BASE).netloc
    return ZlibSession(host=host, remix_userid=remix_userid, remix_userkey=remix_userkey)
