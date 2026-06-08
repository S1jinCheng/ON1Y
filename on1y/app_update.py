"""Check GitHub Releases for desktop app updates (phase 1: notify + manual install)."""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from on1y import __version__

logger = logging.getLogger(__name__)

_DEFAULT_REPO = "S1jinCheng/ON1Y"
_CACHE_TTL_SECONDS = 3600
_cache: dict[str, Any] = {"expires_at": 0.0, "payload": None}


def is_bundled_release() -> bool:
    """True for PyInstaller / packaged desktop installs; dev conda builds skip update checks."""
    dev_check = os.environ.get("ON1Y_UPDATE_CHECK_DEV", "").strip().lower()
    if dev_check in {"1", "true", "yes", "on"}:
        return True
    flag = os.environ.get("ON1Y_BUNDLED", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    return bool(getattr(sys, "frozen", False))


def parse_version(text: str | None) -> tuple[int, int, int]:
    if not text:
        return (0, 0, 0)
    cleaned = str(text).strip().lstrip("vV")
    parts = cleaned.split(".")
    nums: list[int] = []
    for index in range(3):
        if index >= len(parts):
            nums.append(0)
            continue
        match = re.match(r"(\d+)", parts[index])
        nums.append(int(match.group(1)) if match else 0)
    return (nums[0], nums[1], nums[2])


def version_less_than(current: str, latest: str) -> bool:
    return parse_version(current) < parse_version(latest)


def _github_repo() -> str:
    raw = os.environ.get("ON1Y_UPDATE_GITHUB_REPO", _DEFAULT_REPO).strip()
    return raw or _DEFAULT_REPO


def _pick_setup_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".exe") and "setup" in name:
            return asset
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".exe"):
            return asset
    return None


def _fetch_latest_release(repo: str) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "On1y-desktop-update",
    }
    with httpx.Client(timeout=20.0, headers=headers, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("unexpected GitHub release payload")
    return payload


def check_app_update(*, force: bool = False) -> dict[str, Any]:
    current = __version__
    checked_at = datetime.now(timezone.utc).isoformat()
    base: dict[str, Any] = {
        "check_enabled": True,
        "current_version": current,
        "has_update": False,
        "checked_at": checked_at,
    }

    if not is_bundled_release():
        return {
            **base,
            "check_enabled": False,
            "reason": "dev_build",
        }

    now = time.monotonic()
    if (
        not force
        and _cache.get("payload") is not None
        and now < float(_cache.get("expires_at") or 0)
    ):
        cached = dict(_cache["payload"])
        cached["current_version"] = current
        cached["checked_at"] = checked_at
        cached["cached"] = True
        return cached

    repo = _github_repo()
    try:
        release = _fetch_latest_release(repo)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {
                **base,
                "reason": "no_releases",
                "release_url": f"https://github.com/{repo}/releases",
            }
        logger.warning("GitHub release check failed: %s", exc)
        return {**base, "error": f"github_http_{exc.response.status_code}"}
    except Exception as exc:
        logger.warning("GitHub release check failed: %s", exc)
        return {**base, "error": str(exc)}

    tag = str(release.get("tag_name") or "").strip()
    latest_version = tag.lstrip("vV") if tag else ""
    assets = release.get("assets") if isinstance(release.get("assets"), list) else []
    asset = _pick_setup_asset([a for a in assets if isinstance(a, dict)])
    download_url = str(asset.get("browser_download_url") or "").strip() if asset else ""
    release_url = str(release.get("html_url") or "").strip() or f"https://github.com/{repo}/releases/latest"
    if not download_url:
        download_url = release_url

    notes = str(release.get("body") or "").strip() or None
    published_at = str(release.get("published_at") or "").strip() or None
    has_update = bool(latest_version) and version_less_than(current, latest_version)

    result: dict[str, Any] = {
        **base,
        "latest_version": latest_version or None,
        "has_update": has_update,
        "release_url": release_url,
        "download_url": download_url,
        "release_notes": notes,
        "published_at": published_at,
        "cached": False,
    }
    _cache["payload"] = dict(result)
    _cache["expires_at"] = now + _CACHE_TTL_SECONDS
    return result
