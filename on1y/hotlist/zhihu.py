"""Fetch and sync Zhihu daily hot list (questions + descriptions + links)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.hotlist.constants import HOTLIST_ZHIHU, HOTLIST_ZHIHU_CURSOR, HOTLIST_ZHIHU_LABEL
from on1y.ingestion.zhihu_follow_list import DEFAULT_HEADERS, _cookie_jar
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.ports.storage import StoragePort
from on1y.utils.platform import PLATFORM_ZHIHU, normalize_url

logger = logging.getLogger(__name__)

ZHIHU_HOTLIST_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"


def _question_web_url(question_id: str | int) -> str:
    return normalize_url(f"https://www.zhihu.com/question/{question_id}")


def _parse_hotlist_entry(entry: dict[str, Any], *, rank: int) -> dict[str, Any] | None:
    target = entry.get("target")
    if not isinstance(target, dict):
        return None
    if str(target.get("type") or "").lower() != "question":
        return None
    question_id = target.get("id")
    title = str(target.get("title") or "").strip()
    if question_id is None or not title:
        return None
    excerpt = str(target.get("excerpt") or "").strip()
    heat = str(entry.get("detail_text") or "").strip()
    created = target.get("created")
    published_iso: str | None = None
    try:
        if created is not None:
            published_iso = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        published_iso = None
    return {
        "question_id": str(question_id),
        "title": title,
        "excerpt": excerpt,
        "heat_text": heat,
        "rank": rank,
        "url": _question_web_url(question_id),
        "published": published_iso,
    }


def fetch_zhihu_hotlist(
    *,
    settings: Settings | None = None,
    limit: int | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    fetch_limit = limit if limit is not None else settings.zhihu_hotlist_limit
    path = settings.zhihu_cookies_path
    jar = _cookie_jar(path)
    if not jar:
        raise ConfigurationError(f"No zhihu.com cookies in {path}")

    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    rows: list[dict[str, Any]] = []
    try:
        assert client is not None
        response = client.get(
            ZHIHU_HOTLIST_URL,
            params={"limit": fetch_limit, "desktop": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload.get("error"), dict):
            message = str(payload["error"].get("message") or payload["error"])
            raise ConfigurationError(f"Zhihu hot list failed: {message}")
        batch = payload.get("data") or []
        for index, entry in enumerate(batch, start=1):
            if not isinstance(entry, dict):
                continue
            parsed = _parse_hotlist_entry(entry, rank=index)
            if parsed is not None:
                rows.append(parsed)
    finally:
        if own_client and client is not None:
            client.close()

    logger.info("Fetched %s Zhihu hot-list question(s)", len(rows))
    return rows


def _format_body_text(*, excerpt: str, url: str, heat_text: str) -> str:
    parts: list[str] = []
    if excerpt.strip():
        parts.append(excerpt.strip())
    footer: list[str] = [f"原文链接：{url}"]
    if heat_text:
        footer.append(f"热度：{heat_text}")
    parts.append("\n---\n" + "\n".join(footer))
    return "\n\n".join(parts)


def _summary_from_excerpt(excerpt: str, *, max_len: int = 280) -> str:
    text = re.sub(r"\s+", " ", excerpt.strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def sync_zhihu_hotlist(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    limit: int | None = None,
    auto_distill: bool = False,
) -> dict[str, Any]:
    from on1y.hotlist.constants import HOTLIST_THEME_SLUG

    settings = settings or get_settings()
    snapshot_date = date.today().isoformat()
    report: dict[str, Any] = {
        "source": HOTLIST_ZHIHU,
        "snapshot_date": snapshot_date,
        "fetched": 0,
        "created": 0,
        "updated": 0,
        "theme_assigned": 0,
        "distilled": 0,
        "errors": [],
    }

    try:
        items = fetch_zhihu_hotlist(settings=settings, limit=limit)
    except Exception as exc:
        logger.warning("Zhihu hot list fetch failed: %s", exc)
        report["errors"].append({"stage": "fetch", "error": str(exc)})
        return report

    report["fetched"] = len(items)
    theme_id = storage.get_theme_id_by_slug(HOTLIST_THEME_SLUG)

    for item in items:
        url = item["url"]
        excerpt = str(item.get("excerpt") or "")
        body_text = _format_body_text(
            excerpt=excerpt,
            url=url,
            heat_text=str(item.get("heat_text") or ""),
        )
        source_meta = {
            "feed_label": HOTLIST_ZHIHU_LABEL,
            "hotlist_source": HOTLIST_ZHIHU,
            "subscription_source": "zhihu_hotlist",
            "entry_title": item["title"],
            "entry_excerpt": excerpt[:2000],
            "hot_rank": item["rank"],
            "heat_text": item.get("heat_text"),
            "question_id": item["question_id"],
            "published": item.get("published") or datetime.now(timezone.utc).isoformat(),
            "snapshot_date": snapshot_date,
        }

        existing = storage.get_raw_by_url(url)
        try:
            raw = storage.upsert_raw_item(
                RawItemCreate(
                    url=url,
                    platform=PLATFORM_ZHIHU,
                    source=SourceType.RSS,
                    raw_title=item["title"],
                    body_text=body_text,
                    content_type=ContentType.ARTICLE,
                    extract_status=ExtractStatus.OK,
                    source_meta=source_meta,
                )
            )
            if existing is None:
                report["created"] += 1
            else:
                report["updated"] += 1

            if theme_id is not None:
                storage.set_item_theme(raw.id, theme_id, source="hotlist")
                report["theme_assigned"] += 1

            summary = _summary_from_excerpt(excerpt)
            if summary:
                storage.upsert_distilled(
                    raw_id=raw.id,
                    summary=summary,
                    key_points=[],
                    topics=[],
                    model=None,
                    prompt_version="hotlist-v1",
                    status="ok",
                    error=None,
                    reader_text=body_text,
                )

            if auto_distill:
                from on1y.distill.processor import distill_raw_item

                try:
                    distill_raw_item(storage, raw.id, force=False)
                    report["distilled"] += 1
                except Exception as exc:
                    report["errors"].append({"url": url, "error": f"distill: {exc}"})
        except Exception as exc:
            logger.warning("Zhihu hot list upsert failed url=%s: %s", url, exc)
            report["errors"].append({"url": url, "error": str(exc)})

    storage.set_rss_feed_state(
        HOTLIST_ZHIHU_CURSOR,
        last_entry_id=snapshot_date,
        last_published=datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z"),
    )
    return report
