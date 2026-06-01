#!/usr/bin/env python3
"""Interactive login → save Playwright storage_state for all supported platforms."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PLATFORMS: dict[str, tuple[str, str]] = {
    "youtube": ("https://www.youtube.com", "youtube.json"),
    "bilibili": ("https://www.bilibili.com", "bilibili.json"),
    "zhihu": ("https://www.zhihu.com", "zhihu.json"),
    "xiaohongshu": ("https://www.xiaohongshu.com", "xiaohongshu.json"),
    "twitter": ("https://x.com", "twitter.json"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Playwright cookies after manual login")
    parser.add_argument(
        "platform",
        choices=list(PLATFORMS.keys()),
        help="Platform to log in",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Headless mode (usually not suitable for manual login)",
    )
    args = parser.parse_args()
    login_url, filename = PLATFORMS[args.platform]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Install Playwright: pip install playwright",
            file=sys.stderr,
        )
        return 1

    from on1y.browser.discover import launch_playwright_chromium

    out_dir = Path(__file__).resolve().parent.parent / "data" / "cookies"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    print(f"Opening browser at {login_url}")
    print("Log in fully, then return here and press Enter.")
    try:
        with sync_playwright() as p:
            browser = launch_playwright_chromium(p, headless=args.headless)
            context = browser.new_context()
            page = context.new_page()
            page.goto(login_url, wait_until="domcontentloaded")
            input("Press Enter after login is complete...")
            context.storage_state(path=str(out_path))
            browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "does not support" in str(exc):
            _print_linux_setup_hint(args.platform)
            return 1
        if "No Chromium/Chrome available" in str(exc):
            _print_linux_setup_hint(args.platform)
            return 1
        raise

    print(f"Saved storage_state to {out_path}")
    return 0


def _print_linux_setup_hint(platform: str) -> None:
    print(
        "\n[On1y] No browser for Playwright.\n"
        "Open-source / Linux setup (recommended):\n\n"
        "  bash scripts/setup_linux_browser.sh\n"
        "  python scripts/export_cookies.py "
        f"{platform}\n\n"
        "Fallback without GUI browser:\n"
        f"  python scripts/import_cookies.py {platform} /path/to/cookies.json\n\n"
        "Details: docs/COOKIES.md\n",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
