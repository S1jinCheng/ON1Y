"""YouTube channel list → feeds.yaml (RSS entries)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

import yaml

from on1y.config import PROJECT_ROOT, Settings, get_settings
from on1y.extract.ytdlp_util import build_ytdlp_opts

YT_RSS_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YT_FEED_LABEL_PREFIX = "yt-"
DEFAULT_CHANNELS_FILE = PROJECT_ROOT / "config" / "youtube_channels.txt"

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_CHANNEL_URL_RE = re.compile(
    r"youtube\.com/(?:channel/(UC[\w-]+)|@([\w.-]+))",
    re.IGNORECASE,
)


def slug_label(channel_id: str, title: str | None) -> str:
    base = (title or channel_id).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40] or channel_id
    return f"{YT_FEED_LABEL_PREFIX}{slug}"


def parse_channel_line(line: str) -> tuple[str, str | None] | None:
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
        parsed = parse_channel_line(line)
        if parsed:
            rows.append(parsed)
    return rows


def channels_from_ytdlp(*, max_channels: int, settings: Settings | None = None) -> list[tuple[str, str | None]]:
    import yt_dlp

    settings = settings or get_settings()
    from on1y.cookies.loader import resolve_cookie_path

    opts = build_ytdlp_opts(cookie_path=resolve_cookie_path("youtube", settings))
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
                logger.warning("yt-dlp could not read %s: %s", feed_url, exc)
                continue
            for entry in info.get("entries") or []:
                if not entry:
                    continue
                channel_id = entry.get("channel_id") or entry.get("id")
                if not channel_id or not str(channel_id).startswith("UC"):
                    url = entry.get("url") or entry.get("webpage_url") or ""
                    parsed = parse_channel_line(str(url))
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
            except Exception:
                continue
    return resolved


def merge_youtube_feeds_yaml(
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
        label = slug_label(channel_id, title)
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
        return len(channels)
    feeds_path.parent.mkdir(parents=True, exist_ok=True)
    feeds_path.write_text(out, encoding="utf-8")
    return len(channels)
