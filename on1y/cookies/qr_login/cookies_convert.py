"""Convert HTTP client cookies to Playwright storage_state."""

from __future__ import annotations

from http.cookiejar import Cookie
from typing import Any

import httpx

from on1y.browser.cookies import normalize_storage_state


def httpx_client_to_storage_state(client: httpx.Client) -> dict[str, Any]:
    cookies: list[dict[str, Any]] = []
    jar = client.cookies.jar
    for cookie in jar:
        if not isinstance(cookie, Cookie):
            continue
        domain = cookie.domain or ""
        if domain and not domain.startswith("."):
            domain = f".{domain.lstrip('.')}"
        entry: dict[str, Any] = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": domain or ".zhihu.com",
            "path": cookie.path or "/",
        }
        if cookie.expires is not None:
            entry["expires"] = float(cookie.expires)
        if cookie.secure:
            entry["secure"] = True
        if cookie.has_nonstandard_attr("HttpOnly") or cookie.name.startswith("__Secure-"):
            entry["httpOnly"] = True
        cookies.append(entry)
    return normalize_storage_state({"cookies": cookies, "origins": []})
