"""Migrate legacy single-user files into user id 1."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from on1y.config import Settings, get_settings
from on1y.user.paths import COOKIE_PLATFORMS, user_cookie_path, user_cookies_dir

logger = logging.getLogger(__name__)


def _copy_if_missing(src: Path, dest: Path) -> bool:
    if not src.is_file() or dest.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def migrate_legacy_files_to_user(user_id: int, *, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    report: dict[str, Any] = {"cookies": [], "profile": False, "subscription": False}
    dest_dir = user_cookies_dir(user_id)

    for platform in COOKIE_PLATFORMS:
        attr = f"{platform}_cookies_path"
        if not hasattr(settings, attr):
            continue
        legacy = getattr(settings, attr)
        dest = user_cookie_path(user_id, platform)
        if _copy_if_missing(legacy, dest):
            report["cookies"].append(platform)

    legacy_cookies = settings.data_dir / "cookies"
    if legacy_cookies.is_dir():
        for platform in COOKIE_PLATFORMS:
            src = legacy_cookies / f"{platform}.json"
            dest = dest_dir / f"{platform}.json"
            if _copy_if_missing(src, dest) and platform not in report["cookies"]:
                report["cookies"].append(platform)

    profile_path = settings.data_dir / "user_profile.json"
    if profile_path.is_file():
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                report["profile_payload"] = data
                report["profile"] = True
        except json.JSONDecodeError:
            logger.warning("Skipping invalid legacy user_profile.json")

    sub_path = settings.data_dir / "subscription_settings.json"
    if sub_path.is_file():
        try:
            data = json.loads(sub_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                report["subscription_payload"] = data
                report["subscription"] = True
        except json.JSONDecodeError:
            logger.warning("Skipping invalid legacy subscription_settings.json")

    llm_path = settings.data_dir / "llm_settings.json"
    if llm_path.is_file():
        from on1y.user.paths import user_llm_settings_path

        dest_llm = user_llm_settings_path(user_id)
        if _copy_if_missing(llm_path, dest_llm):
            report["llm_settings"] = True

    economist_dir = settings.data_dir / "economist"
    if economist_dir.is_dir():
        from on1y.user.paths import user_economist_cache_dir

        dest_econ = user_economist_cache_dir(user_id)
        for epub in economist_dir.glob("*.epub"):
            target = dest_econ / epub.name
            if _copy_if_missing(epub, target):
                report.setdefault("economist_epubs", []).append(epub.name)

    return report
