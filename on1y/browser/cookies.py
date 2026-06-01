"""Load and normalize browser cookies for Playwright."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def is_storage_state(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and "cookies" in data
        and isinstance(data["cookies"], list)
        and "origins" in data
    )


def is_cookie_list(data: Any) -> bool:
    return isinstance(data, list) and (not data or isinstance(data[0], dict) and "name" in data[0])


def load_cookie_file(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    if not path.is_file():
        raise ConfigurationError(
            f"Cookie file not found: {path}. "
            "Export login cookies from your browser — see docs/COOKIES.md"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in cookie file {path}: {exc}") from exc

    if is_storage_state(data) or is_cookie_list(data):
        return data
    raise ConfigurationError(
        f"Unsupported cookie format in {path}. "
        "Use Playwright storage_state JSON or a cookie object array."
    )


def _normalize_same_site(value: Any) -> str | None:
    """Map Cookie-Editor / Chrome export values to Playwright sameSite."""
    if value is None or value == "":
        return None
    key = str(value).lower().replace("_", "")
    if key in ("norestriction", "none"):
        return "None"
    if key == "lax":
        return "Lax"
    if key == "strict":
        return "Strict"
    if key in ("unspecified", "null"):
        return None
    return str(value)


def normalize_cookie_list(
    cookies: list[dict[str, Any]],
    default_domain: str,
) -> list[dict[str, Any]]:
    """Ensure cookies satisfy Playwright add_cookies requirements."""
    normalized: list[dict[str, Any]] = []
    for raw in cookies:
        if "name" not in raw or "value" not in raw:
            continue
        cookie: dict[str, Any] = {
            "name": str(raw["name"]),
            "value": str(raw["value"]),
            "domain": str(raw.get("domain") or default_domain),
            "path": str(raw.get("path") or "/"),
        }
        expires = raw.get("expires")
        if expires is None and raw.get("expirationDate") is not None:
            expires = raw["expirationDate"]
        if expires is not None and not raw.get("session"):
            cookie["expires"] = expires
        if raw.get("httpOnly") is not None:
            cookie["httpOnly"] = bool(raw["httpOnly"])
        if raw.get("secure") is not None:
            cookie["secure"] = bool(raw["secure"])
        same_site = _normalize_same_site(raw.get("sameSite"))
        if same_site is not None:
            cookie["sameSite"] = same_site
        normalized.append(cookie)
    return normalized


def seed_url_for_domain(domain: str) -> str:
    host = domain.lstrip(".")
    return f"https://{host}/"
