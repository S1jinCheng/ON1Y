"""Sync The Economist daily digest into the hot-list column (RSS)."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.hotlist.constants import (
    HOTLIST_ECONOMIST,
    HOTLIST_ECONOMIST_CURSOR,
    HOTLIST_ECONOMIST_LABEL,
)
from on1y.hotlist.zhihu import _normalize_snapshot_date
from on1y.ingestion.rss import FeedConfig, _entry_published, parse_feed
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.ports.storage import StoragePort
from on1y.utils.platform import normalize_url

logger = logging.getLogger(__name__)

PLATFORM_ECONOMIST = "economist"


def _strip_html(text: str) -> str:
    if not text or "<" not in text:
        return re.sub(r"\s+", " ", text.strip())
    return re.sub(r"\s+", " ", BeautifulSoup(text, "lxml").get_text(" ", strip=True))


def _entry_excerpt(entry: dict[str, Any]) -> str:
    raw = entry.get("summary") or entry.get("description") or entry.get("content") or ""
    if isinstance(raw, list) and raw:
        raw = raw[0].get("value", "") if isinstance(raw[0], dict) else str(raw[0])
    return _strip_html(str(raw))


def _is_github_economist_feed(url: str) -> bool:
    lower = url.lower()
    return "github.com" in lower and "awesome-english-ebooks" in lower


def fetch_economist_hotlist(
    *,
    settings: Settings | None = None,
    limit: int | None = None,
    snapshot_date: str | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    feed_url = settings.economist_hotlist_rss_url.strip()
    if not feed_url:
        raise ConfigurationError("economist_hotlist_rss_url is empty")

    if _is_github_economist_feed(feed_url):
        from on1y.hotlist.github_economist import fetch_economist_github_hotlist

        return fetch_economist_github_hotlist(
            settings=settings,
            limit=limit,
            snapshot_date=snapshot_date,
            feed_url=feed_url,
        )

    fetch_limit = limit if limit is not None else settings.economist_hotlist_limit
    feed = FeedConfig(
        url=feed_url,
        label=HOTLIST_ECONOMIST_LABEL,
        enabled=True,
    )

    parsed = parse_feed(feed)
    if parsed.bozo and not parsed.entries:
        raise ConfigurationError(
            f"Economist RSS parse failed: {parsed.bozo_exception or 'no entries'}"
        )

    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(parsed.entries[:fetch_limit], start=1):
        link = entry.get("link")
        if not link:
            continue
        title = _strip_html(str(entry.get("title") or "").strip())
        if not title:
            continue
        entry_id = str(entry.get("id") or link)
        excerpt = _entry_excerpt(entry)
        published = _entry_published(entry)
        rows.append(
            {
                "entry_id": entry_id,
                "title": title,
                "excerpt": excerpt,
                "heat_text": _format_heat_text(published),
                "rank": index,
                "url": normalize_url(str(link)),
                "published": published,
            }
        )

    logger.info("Fetched %s Economist hot-list article(s)", len(rows))
    return rows


def _format_heat_text(published: str | None) -> str:
    if not published:
        return ""
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return published[:32]


def _format_body_text(*, excerpt: str, url: str, heat_text: str) -> str:
    parts: list[str] = []
    if excerpt.strip():
        parts.append(excerpt.strip())
    footer: list[str] = [f"原文链接：{url}"]
    if heat_text:
        footer.append(f"发布时间：{heat_text}")
    parts.append("\n---\n" + "\n".join(footer))
    return "\n\n".join(parts)


def _summary_from_excerpt(excerpt: str, *, max_len: int = 280) -> str:
    text = re.sub(r"\s+", " ", excerpt.strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def sync_economist_hotlist(
    storage: StoragePort,
    *,
    settings: Settings | None = None,
    limit: int | None = None,
    auto_distill: bool = False,
    auto_tag: bool | None = None,
    snapshot_date: str | date | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if auto_tag is None:
        auto_tag = settings.economist_hotlist_auto_tag
    snapshot_date = _normalize_snapshot_date(snapshot_date)
    report: dict[str, Any] = {
        "source": HOTLIST_ECONOMIST,
        "snapshot_date": snapshot_date,
        "fetched": 0,
        "created": 0,
        "updated": 0,
        "distilled": 0,
        "tagged": 0,
        "errors": [],
    }

    try:
        items = fetch_economist_hotlist(
            settings=settings, limit=limit, snapshot_date=snapshot_date
        )
    except Exception as exc:
        logger.warning("Economist hot list fetch failed: %s", exc)
        report["errors"].append({"stage": "fetch", "error": str(exc)})
        return report

    report["fetched"] = len(items)

    for item in items:
        epub_url = str(item.get("epub_url") or item.get("url") or "")
        url = epub_url
        edition_date = str(item.get("edition_date") or snapshot_date)
        excerpt = ""
        body_text = ""
        preview_meta: dict[str, Any] = {}
        snap = edition_date or snapshot_date

        existing = storage.get_raw_by_url(url)
        if existing is None and hasattr(storage, "get_hotlist_raw_id"):
            rid = storage.get_hotlist_raw_id(  # type: ignore[attr-defined]
                hotlist_source=HOTLIST_ECONOMIST,
                question_id=str(item["entry_id"]),
            )
            if rid is not None:
                existing = storage.get_raw_by_id(rid)
        if existing is None:
            legacy_pdf = url.replace(".epub", ".pdf") if url.endswith(".epub") else ""
            if legacy_pdf:
                existing = storage.get_raw_by_url(legacy_pdf)
        prior_meta = dict(existing.source_meta or {}) if existing else {}
        from on1y.hotlist.economist_preview_store import (
            _distilled_summary,
            preview_is_complete,
        )

        reuse_preview = (
            existing is not None
            and preview_is_complete(existing.body_text, prior_meta)
        )
        if reuse_preview and existing is not None:
            body_text = str(existing.body_text or "")
            excerpt = str(prior_meta.get("entry_excerpt") or "")[:400]
            summary_text = _distilled_summary(storage, existing.id) or excerpt
            preview_meta = {
                "summary": summary_text,
                "chapters": prior_meta.get("key_points") or [],
                "chapter_count": prior_meta.get("chapter_count"),
                "preview_chars": prior_meta.get("preview_chars"),
            }
            logger.info("Economist %s: reusing stored preview (raw_id=%s)", edition_date, existing.id)
        elif epub_url and edition_date:
            from on1y.hotlist.epub_preview import build_economist_preview

            try:
                preview_meta = build_economist_preview(
                    epub_url, edition_date, settings=settings
                )
                body_text = str(preview_meta.get("body_text") or "")
                excerpt = str(preview_meta.get("excerpt") or "")
                summary_text = str(preview_meta.get("summary") or excerpt)
                preview_meta["summary"] = summary_text
            except Exception as exc:
                logger.warning("Economist EPUB preview failed %s: %s", edition_date, exc)
                from on1y.hotlist.epub_preview import (
                    format_economist_reader_body,
                    format_economist_summary,
                )

                summary_text = format_economist_summary(
                    edition_date=edition_date,
                    chapters=[],
                    preview_text="",
                    parse_error=str(exc),
                )
                body_text = format_economist_reader_body(
                    chapters=[], preview_text="", parse_error=str(exc)
                )
                preview_meta = {"summary": summary_text}
                excerpt = summary_text[:400]
                report["errors"].append({"url": url, "error": f"epub_preview: {exc}"})
        elif epub_url:
            body_text = ""
            excerpt = item["title"]
            summary_text = excerpt

        from on1y.hotlist.epub_preview import resolve_economist_epub_cache_path

        cached_path = (
            resolve_economist_epub_cache_path(settings, edition_date)
            if edition_date
            else None
        )
        source_meta = {
            "feed_label": HOTLIST_ECONOMIST_LABEL,
            "hotlist_source": HOTLIST_ECONOMIST,
            "subscription_source": "economist_hotlist",
            "entry_title": item["title"],
            "entry_excerpt": excerpt,
            "hot_rank": item["rank"],
            "heat_text": item.get("heat_text"),
            "question_id": item["entry_id"],
            "epub_url": epub_url,
            "iso_year": item.get("iso_year"),
            "iso_week": item.get("iso_week"),
            "edition_date": edition_date,
            "chapter_count": preview_meta.get("chapter_count"),
            "preview_chars": preview_meta.get("preview_chars"),
            "epub_preview_ok": preview_is_complete(
                body_text,
                {**prior_meta, "preview_chars": preview_meta.get("preview_chars")},
            ),
            "epub_cached": cached_path is not None,
            "published": item.get("published") or datetime.now(timezone.utc).isoformat(),
            "snapshot_date": snap,
        }
        if preview_meta.get("summary"):
            source_meta["epub_preview_ok"] = True

        try:
            if existing is not None and existing.url != url:
                conflict = storage.get_raw_by_url(url)
                if conflict is not None and conflict.id != existing.id:
                    existing = conflict
                elif hasattr(storage, "update_raw_url"):
                    try:
                        storage.update_raw_url(existing.id, url)  # type: ignore[attr-defined]
                        existing = storage.get_raw_by_id(existing.id)
                    except Exception as exc:
                        logger.warning("Could not migrate Economist url: %s", exc)
            raw = storage.upsert_raw_item(
                RawItemCreate(
                    url=url,
                    platform=PLATFORM_ECONOMIST,
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

            storage.detach_hotlist_item(raw.id)

            if hasattr(storage, "upsert_hotlist_snapshot"):
                storage.upsert_hotlist_snapshot(  # type: ignore[attr-defined]
                    hotlist_source=HOTLIST_ECONOMIST,
                    snapshot_date=snap,
                    question_id=str(item["entry_id"]),
                    raw_id=raw.id,
                    heat_text=str(item.get("heat_text") or "").strip() or None,
                    title=item["title"],
                    excerpt=excerpt,
                    sort_order=int(item["rank"]),
                )

            summary_for_distill = str(
                preview_meta.get("summary") or excerpt or item["title"]
            ).strip()
            skip_distill = (
                reuse_preview
                and existing is not None
                and bool(_distilled_summary(storage, existing.id))
            )
            if (summary_for_distill or body_text.strip()) and not skip_distill:
                storage.upsert_distilled(
                    raw_id=raw.id,
                    summary=summary_for_distill or item["title"],
                    key_points=list(preview_meta.get("chapters") or [])[:12],
                    topics=[],
                    model=None,
                    prompt_version="hotlist-v1",
                    status="ok",
                    error=None,
                    reader_text=body_text,
                )

            if auto_tag:
                from on1y.hotlist.tags import distill_hotlist_tags, needs_hotlist_tags

                if needs_hotlist_tags(prior_meta, snapshot_date=snapshot_date):
                    try:
                        distill_hotlist_tags(
                            storage,
                            raw.id,
                            title=item["title"],
                            excerpt=excerpt,
                            heat_text=str(item.get("heat_text") or ""),
                            snapshot_date=snapshot_date,
                        )
                        report["tagged"] += 1
                    except Exception as exc:
                        report["errors"].append({"url": url, "error": f"tags: {exc}"})

            if auto_distill:
                from on1y.distill.processor import distill_raw_item

                try:
                    distill_raw_item(storage, raw.id, force=False)
                    report["distilled"] += 1
                except Exception as exc:
                    report["errors"].append({"url": url, "error": f"distill: {exc}"})
        except Exception as exc:
            logger.warning("Economist hot list upsert failed url=%s: %s", url, exc)
            report["errors"].append({"url": url, "error": str(exc)})

    storage.set_rss_feed_state(
        HOTLIST_ECONOMIST_CURSOR,
        last_entry_id=snapshot_date,
        last_published=datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z"),
    )
    return report
