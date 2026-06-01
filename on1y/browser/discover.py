"""Discover system Chrome/Chromium for Playwright (no bundled browser required)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Reduce automation fingerprint (Zhihu / XHS anti-bot)
STEALTH_LAUNCH_ARGS = ("--disable-blink-features=AutomationControlled",)
STEALTH_IGNORE_DEFAULT_ARGS = ("--enable-automation",)

STEALTH_INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)

# Common paths on Debian/Ubuntu/WSL
CHROMIUM_CANDIDATES = (
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
)


def find_chromium_executable() -> Path | None:
    for candidate in CHROMIUM_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    found = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    return Path(found) if found else None


def _launch_kwargs(*, headless: bool) -> dict:
    return {
        "headless": headless,
        "args": list(STEALTH_LAUNCH_ARGS),
        "ignore_default_args": list(STEALTH_IGNORE_DEFAULT_ARGS),
    }


def launch_playwright_chromium(playwright: object, *, headless: bool = False) -> object:
    """
    Launch browser: prefer system Chrome/Chromium, then Playwright channels, last bundled.
    Uses stealth launch flags to avoid common anti-bot redirects (e.g. Zhihu /account/unhuman).
    Returns Playwright Browser instance.
    """
    chromium = playwright.chromium  # type: ignore[attr-defined]
    errors: list[str] = []
    launch_kw = _launch_kwargs(headless=headless)

    for channel in ("chrome", "chromium", "msedge"):
        try:
            browser = chromium.launch(channel=channel, **launch_kw)
            logger.info("Launched Playwright channel=%s", channel)
            return browser
        except Exception as exc:
            errors.append(f"channel {channel}: {exc}")

    executable = find_chromium_executable()
    if executable is not None:
        try:
            browser = chromium.launch(executable_path=str(executable), **launch_kw)
            logger.info("Launched system browser at %s", executable)
            return browser
        except Exception as exc:
            errors.append(f"executable {executable}: {exc}")

    try:
        return chromium.launch(**launch_kw)
    except Exception as exc:
        errors.append(f"bundled: {exc}")
        raise RuntimeError(
            "No Chromium/Chrome available. Install Google Chrome or Chromium on Linux, "
            "or run: playwright install chromium\n"
            + "\n".join(errors[:3])
        ) from exc
