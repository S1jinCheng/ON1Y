#!/usr/bin/env python3
"""
Export cookies via yt-dlp from a local browser profile (no Playwright UI).

Works when Linux Chrome/Chromium is installed and you are logged in there.
On WSL without Linux browsers, use scripts/import_cookies.py instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLATFORMS = ("youtube", "bilibili", "zhihu", "xiaohongshu", "twitter")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export cookies from local browser via yt-dlp")
    parser.add_argument("platform", choices=PLATFORMS)
    parser.add_argument(
        "--browser",
        default="chrome",
        help="Browser name for yt-dlp (chrome, chromium, edge, brave, firefox)",
    )
    parser.add_argument("--profile", default=None, help="Browser profile name/path")
    args = parser.parse_args()

    try:
        from yt_dlp.cookies import extract_cookies_from_browser
    except ImportError:
        print("yt-dlp is required.", file=sys.stderr)
        return 1

    try:
        cookies, browser_key = extract_cookies_from_browser(args.browser, args.profile)
    except Exception as exc:
        print(f"Failed to read cookies from {args.browser}: {exc}", file=sys.stderr)
        print(
            "\nWSL tip: Linux browser cookies are usually not in Windows Chrome.\n"
            "Use Cookie-Editor extension + scripts/import_cookies.py instead.\n"
            "See docs/COOKIES.md section 'WSL / Ubuntu 26'.",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(__file__).resolve().parent.parent / "data" / "cookies"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.platform}.json"
    state = {"cookies": cookies, "origins": []}
    out_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(cookies)} cookies from {browser_key} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
