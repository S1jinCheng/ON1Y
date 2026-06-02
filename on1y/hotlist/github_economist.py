"""The Economist weekly editions from hehonghui/awesome-english-ebooks (GitHub commits feed)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode

import feedparser
import httpx

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.ingestion.rss import USER_AGENT, _entry_published

logger = logging.getLogger(__name__)

GITHUB_REPO = "hehonghui/awesome-english-ebooks"
GITHUB_ECONOMIST_COMMITS_ATOM = (
    "https://github.com/hehonghui/awesome-english-ebooks/commits/master/01_economist.atom"
)
GITHUB_COMMITS_API = (
    "https://api.github.com/repos/hehonghui/awesome-english-ebooks/commits"
)
GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/hehonghui/awesome-english-ebooks/master"
)
_EDITION_TITLE_RE = re.compile(
    r"^(?:the\s+economist\s+)?(\d{4})\.(\d{2})\.(\d{2})\s*$",
    re.IGNORECASE,
)
_EDITION_IN_TEXT_RE = re.compile(
    r"(?:the\s+economist\s+)?(\d{4})\.(\d{2})\.(\d{2})",
    re.IGNORECASE,
)


def _edition_iso(year: str, month: str, day: str) -> str:
    return f"{year}-{month}-{day}"


def _edition_folder(year: str, month: str, day: str) -> str:
    return f"te_{year}.{month}.{day}"


def _raw_base(settings: Settings) -> str:
    custom = (settings.economist_github_raw_base or "").strip().rstrip("/")
    return custom or GITHUB_RAW_BASE


def _epub_url(folder: str, *, raw_base: str) -> str:
    edition = folder[3:] if folder.startswith("te_") else folder
    return f"{raw_base}/01_economist/{folder}/TheEconomist.{edition}.epub"


def _week_title(*, iso_year: int, iso_week: int) -> str:
    return f"经济学人 {iso_year}年第{iso_week}周"


def _parse_edition_title(title: str) -> tuple[str, str, str] | None:
    text = re.sub(r"\s+", " ", (title or "").strip())
    match = _EDITION_TITLE_RE.match(text)
    if match:
        return match.group(1), match.group(2), match.group(3)
    found = _EDITION_IN_TEXT_RE.search(text)
    if found:
        return found.group(1), found.group(2), found.group(3)
    return None


def _github_client(settings: Settings) -> httpx.Client:
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(max(settings.http_timeout_seconds, 90.0)),
        "follow_redirects": True,
        "headers": {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    }
    if settings.ytdlp_proxy:
        kwargs["proxy"] = settings.ytdlp_proxy
    return httpx.Client(**kwargs)


def _fetch_text(url: str, settings: Settings) -> str:
    with _github_client(settings) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _parse_atom_feed(url: str, settings: Settings) -> Any:
    try:
        body = _fetch_text(url, settings)
        return feedparser.parse(body)
    except Exception as exc:
        logger.warning(
            "Economist atom HTTP fetch failed (%s), trying feedparser direct", exc
        )
        return feedparser.parse(url, agent=USER_AGENT)


def _row_from_edition(
    *,
    year: str,
    month: str,
    day: str,
    published: str | None,
    raw_base: str,
    rank: int,
) -> dict[str, Any]:
    edition_iso = _edition_iso(year, month, day)
    folder = _edition_folder(year, month, day)
    epub = _epub_url(folder, raw_base=raw_base)
    d = date.fromisoformat(edition_iso)
    iso_year, iso_week, _ = d.isocalendar()
    return {
        "entry_id": f"github-{folder}",
        "title": _week_title(iso_year=iso_year, iso_week=iso_week),
        "excerpt": "",
        "heat_text": edition_iso,
        "rank": rank,
        "url": epub,
        "epub_url": epub,
        "edition_date": edition_iso,
        "iso_year": iso_year,
        "iso_week": iso_week,
        "published": published or datetime.now(timezone.utc).isoformat(),
    }


def _rows_from_atom(
    parsed: Any,
    *,
    snapshot_date: str,
    fetch_limit: int,
    raw_base: str,
) -> list[dict[str, Any]]:
    target_day = (snapshot_date or "").strip()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in parsed.entries:
        title = str(entry.get("title") or "")
        parts = _parse_edition_title(title)
        if not parts:
            continue
        year, month, day = parts
        edition_iso = _edition_iso(year, month, day)
        if edition_iso in seen:
            continue
        if target_day and edition_iso != target_day:
            continue
        seen.add(edition_iso)
        rows.append(
            _row_from_edition(
                year=year,
                month=month,
                day=day,
                published=_entry_published(entry),
                raw_base=raw_base,
                rank=len(rows) + 1,
            )
        )
        if len(rows) >= fetch_limit:
            break
    return rows


def _rows_from_github_api(
    *,
    settings: Settings,
    snapshot_date: str,
    fetch_limit: int,
    raw_base: str,
) -> list[dict[str, Any]]:
    target_day = (snapshot_date or "").strip()
    query = urlencode({"path": "01_economist", "sha": "master", "per_page": "100"})
    url = f"{GITHUB_COMMITS_API}?{query}"
    with _github_client(settings) as client:
        response = client.get(url)
        response.raise_for_status()
        commits = response.json()
    if not isinstance(commits, list):
        return []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in commits:
        if not isinstance(item, dict):
            continue
        commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        message = str(commit.get("message") or "")
        parts = _parse_edition_title(message.split("\n", 1)[0])
        if not parts:
            parts = _parse_edition_title(message)
        if not parts:
            continue
        year, month, day = parts
        edition_iso = _edition_iso(year, month, day)
        if edition_iso in seen:
            continue
        if target_day and edition_iso != target_day:
            continue
        seen.add(edition_iso)
        committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
        published = str(committer.get("date") or "") or None
        rows.append(
            _row_from_edition(
                year=year,
                month=month,
                day=day,
                published=published,
                raw_base=raw_base,
                rank=len(rows) + 1,
            )
        )
        if len(rows) >= fetch_limit:
            break
    return rows


def fetch_economist_github_hotlist(
    *,
    settings: Settings | None = None,
    limit: int | None = None,
    snapshot_date: str | None = None,
    feed_url: str | None = None,
) -> list[dict[str, Any]]:
    """Weekly Economist issues from GitHub commit feed (hehonghui/awesome-english-ebooks)."""
    settings = settings or get_settings()
    fetch_limit = limit if limit is not None else settings.economist_hotlist_limit
    url = (feed_url or settings.economist_hotlist_rss_url or GITHUB_ECONOMIST_COMMITS_ATOM).strip()
    if not url:
        raise ConfigurationError("economist_hotlist_rss_url is empty")

    snap = (snapshot_date or "").strip()
    raw_base = _raw_base(settings)

    rows: list[dict[str, Any]] = []
    try:
        parsed = _parse_atom_feed(url, settings)
        if parsed.bozo and not parsed.entries:
            logger.warning(
                "Economist atom parse issue: %s", parsed.bozo_exception or "no entries"
            )
        else:
            rows = _rows_from_atom(
                parsed, snapshot_date=snap, fetch_limit=fetch_limit, raw_base=raw_base
            )
    except Exception as exc:
        logger.warning("Economist atom feed failed: %s", exc)

    if not rows:
        try:
            rows = _rows_from_github_api(
                settings=settings,
                snapshot_date=snap,
                fetch_limit=fetch_limit,
                raw_base=raw_base,
            )
            if rows:
                logger.info("Economist editions loaded via GitHub API (%s)", len(rows))
        except Exception as exc:
            logger.warning("Economist GitHub API fallback failed: %s", exc)

    if not rows:
        hint = (
            "无法访问 GitHub（连接超时）。请在 .env 设置 ON1Y_YTDLP_PROXY=你的代理，"
            "或配置 ON1Y_ECONOMIST_GITHUB_RAW_BASE / ON1Y_ECONOMIST_HOTLIST_RSS_URL 镜像。"
        )
        raise ConfigurationError(hint)

    logger.info("Fetched %s Economist GitHub edition(s)", len(rows))
    return rows


def fetch_latest_economist_edition(
    *,
    settings: Settings | None = None,
    feed_url: str | None = None,
) -> dict[str, Any] | None:
    """Newest weekly edition from the GitHub commit feed (first matching entry)."""
    rows = fetch_economist_github_hotlist(
        settings=settings,
        limit=1,
        snapshot_date=None,
        feed_url=feed_url,
    )
    return rows[0] if rows else None
