#!/usr/bin/env python3
"""
Import cookies from a browser extension JSON export into data/cookies/<platform>.json.

Use when Playwright cannot run in WSL (e.g. ubuntu 26.04):
  1. Install extension "Cookie-Editor" or "EditThisCookie" in Chrome/Edge
  2. Log in on the target site, export cookies as JSON
  3. Run: python scripts/import_cookies.py youtube ~/Downloads/cookies.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PLATFORMS = ("youtube", "bilibili", "zhihu", "xiaohongshu", "twitter")

_DEFAULT_DOMAIN = {
    "youtube": ".youtube.com",
    "bilibili": ".bilibili.com",
    "zhihu": ".zhihu.com",
    "xiaohongshu": ".xiaohongshu.com",
    "twitter": ".x.com",
}


def _normalize_to_storage_state(data: Any, *, platform: str) -> dict[str, Any]:
    from on1y.browser.cookies import normalize_cookie_list

    if isinstance(data, dict) and "cookies" in data:
        raw_cookies = data["cookies"]
        origins = data.get("origins", [])
    elif isinstance(data, list):
        raw_cookies = data
        origins = []
    else:
        raise ValueError("JSON must be a cookie array or Playwright storage_state object")

    domain = _DEFAULT_DOMAIN.get(platform, "")
    cookies = normalize_cookie_list(raw_cookies, domain)
    return {"cookies": cookies, "origins": origins}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import browser extension cookie JSON")
    parser.add_argument("platform", choices=PLATFORMS)
    parser.add_argument("source", type=Path, help="Path to exported JSON file")
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"File not found: {args.source}", file=sys.stderr)
        return 1

    try:
        data = json.loads(args.source.read_text(encoding="utf-8"))
        state = _normalize_to_storage_state(data, platform=args.platform)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid cookie file: {exc}", file=sys.stderr)
        return 1

    if not state["cookies"]:
        print("No cookies found in file.", file=sys.stderr)
        return 1

    out_dir = Path(__file__).resolve().parent.parent / "data" / "cookies"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.platform}.json"
    out_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(state['cookies'])} cookies to {out_path}")
    print("Verify: on1y cookies status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
