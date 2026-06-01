#!/usr/bin/env python3
"""
Generate YouTube channel RSS entries in config/feeds.yaml from subscriptions.

Ways to supply channels (first match wins):
  1. yt-dlp + login cookies: https://www.youtube.com/feed/channels
  2. --from-file config/youtube_channels.txt (one channel URL or UC... id per line)

Re-export YouTube cookies while logged in (must include .google.com session cookies).
See docs/COOKIES.md and docs/RSS.md.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHANNELS_FILE = PROJECT_ROOT / "config" / "youtube_channels.txt"
DEFAULT_FEEDS_PATH = PROJECT_ROOT / "config" / "feeds.yaml"
YT_RSS_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YT_FEED_LABEL_PREFIX = "yt-"

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_CHANNEL_URL_RE = re.compile(
    r"youtube\.com/(?:channel/(UC[\w-]+)|@([\w.-]+))",
    re.IGNORECASE,
)


def _slug_label(channel_id: str, title: str | None) -> str:
    base = (title or channel_id).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40] or channel_id
    return f"{YT_FEED_LABEL_PREFIX}{slug}"


def _parse_channel_line(line: str) -> tuple[str, str | None] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if _CHANNEL_ID_RE.match(line):
        return line, None
    match = _CHANNEL_URL_RE.search(line)
    if match:
        if match.group(1):
            return match.group(1), None
        return line, match.group(2)
    return None


def channels_from_file(path: Path) -> list[tuple[str, str | None]]:
    if not path.is_file():
        raise FileNotFoundError(f"Channels file not found: {path}")
    rows: list[tuple[str, str | None]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_channel_line(line)
        if parsed:
            rows.append(parsed)
    return rows


def channels_from_ytdlp(*, max_channels: int) -> list[tuple[str, str | None]]:
    import yt_dlp

    from on1y.config import get_settings
    from on1y.extract.ytdlp_util import build_ytdlp_opts

    settings = get_settings()
    opts = build_ytdlp_opts(cookie_path=settings.youtube_cookies_path)
    opts.update(
        {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlistend": max_channels,
        }
    )

    seen: set[str] = set()
    rows: list[tuple[str, str | None]] = []

    with yt_dlp.YoutubeDL(opts) as ydl:
        for feed_url in (
            "https://www.youtube.com/feed/channels",
            "https://www.youtube.com/feed/subscriptions",
        ):
            try:
                info = ydl.extract_info(feed_url, download=False)
            except Exception as exc:
                print(f"yt-dlp could not read {feed_url}: {exc}", file=sys.stderr)
                continue
            for entry in info.get("entries") or []:
                if not entry:
                    continue
                channel_id = entry.get("channel_id") or entry.get("id")
                if not channel_id or not str(channel_id).startswith("UC"):
                    url = entry.get("url") or entry.get("webpage_url") or ""
                    parsed = _parse_channel_line(str(url))
                    if parsed:
                        channel_id, _ = parsed
                    else:
                        continue
                channel_id = str(channel_id)
                if channel_id in seen:
                    continue
                seen.add(channel_id)
                title = entry.get("channel") or entry.get("title")
                rows.append((channel_id, str(title) if title else None))
                if len(rows) >= max_channels:
                    return rows
    return rows


def resolve_channel_ids(rows: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    import yt_dlp

    from on1y.extract.ytdlp_util import build_ytdlp_opts

    resolved: list[tuple[str, str]] = []
    opts = build_ytdlp_opts()
    opts.update({"quiet": True, "no_warnings": True, "extract_flat": True})

    with yt_dlp.YoutubeDL(opts) as ydl:
        for item, title in rows:
            if _CHANNEL_ID_RE.match(item):
                resolved.append((item, title or item))
                continue
            try:
                info = ydl.extract_info(item, download=False)
                cid = info.get("channel_id") or info.get("id")
                if cid and str(cid).startswith("UC"):
                    resolved.append((str(cid), title or info.get("title") or str(cid)))
            except Exception as exc:
                print(f"Skip {item}: {exc}", file=sys.stderr)
    return resolved


def merge_feeds_yaml(
    channels: list[tuple[str, str]],
    *,
    feeds_path: Path,
    enabled: bool,
    dry_run: bool,
) -> int:
    if feeds_path.is_file():
        data = yaml.safe_load(feeds_path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    feeds = list(data.get("feeds") or [])
    feeds = [f for f in feeds if not str(f.get("label", "")).startswith(YT_FEED_LABEL_PREFIX)]

    for channel_id, title in channels:
        label = _slug_label(channel_id, title)
        feeds.append(
            {
                "url": YT_RSS_TEMPLATE.format(channel_id=channel_id),
                "label": label,
                "enabled": enabled,
            }
        )

    data["feeds"] = feeds
    out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    if dry_run:
        print(out)
        return len(channels)
    feeds_path.parent.mkdir(parents=True, exist_ok=True)
    feeds_path.write_text(out, encoding="utf-8")
    return len(channels)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync YouTube subscription channels into feeds.yaml")
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help=f"Text file with channel URLs/IDs (default: {DEFAULT_CHANNELS_FILE})",
    )
    parser.add_argument("--feeds", type=Path, default=DEFAULT_FEEDS_PATH, help="feeds.yaml path")
    parser.add_argument("--max", type=int, default=50, help="Max channels to add")
    parser.add_argument("--no-ytdlp", action="store_true", help="Do not try yt-dlp subscription feeds")
    parser.add_argument("--dry-run", action="store_true", help="Print YAML only")
    parser.add_argument("--disabled", action="store_true", help="Add feeds as enabled: false")
    args = parser.parse_args()

    rows: list[tuple[str, str | None]] = []
    if not args.no_ytdlp and args.from_file is None:
        rows = channels_from_ytdlp(max_channels=args.max)
        if rows:
            print(f"yt-dlp discovered {len(rows)} channel(s)")

    if not rows and (args.from_file is not None or DEFAULT_CHANNELS_FILE.is_file()):
        path = args.from_file or DEFAULT_CHANNELS_FILE
        rows = channels_from_file(path)
        print(f"Read {len(rows)} channel(s) from {path}")

    if not rows:
        print(
            "No channels found.\n"
            "1) Re-export YouTube cookies while logged in (Cookie-Editor on youtube.com).\n"
            "2) Or create config/youtube_channels.txt — one channel URL or UC... id per line.\n"
            "   See config/youtube_channels.txt.example",
            file=sys.stderr,
        )
        return 1

    channels = resolve_channel_ids(rows[: args.max])
    if not channels:
        print("Could not resolve any channel IDs.", file=sys.stderr)
        return 1

    count = merge_feeds_yaml(
        channels,
        feeds_path=args.feeds,
        enabled=not args.disabled,
        dry_run=args.dry_run,
    )
    print(f"{'Would add' if args.dry_run else 'Added'} {count} YouTube feed(s) to {args.feeds}")
    print("Next: on1y rss feeds && on1y rss poll && on1y rss run --limit 5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
