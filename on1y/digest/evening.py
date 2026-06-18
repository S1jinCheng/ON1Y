"""Evening digest: daily stats + optional LLM narrative summary."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from on1y.hotlist.sql import is_feed_row_sql
from on1y.knowledge.notes import has_user_note
from on1y.knowledge.read_state import is_read_meta, utc_now_iso
from on1y.stats.overview import _content_kind, _effective_date, _parse_ingested_dt
from on1y.stats.timezone_util import stats_timezone
from on1y.user.paths import user_dir
from on1y.user.profile import load_user_profile
from on1y.utils.json_util import loads_meta

logger = logging.getLogger(__name__)

_STATS_TZ = stats_timezone()


def today_digest_date() -> str:
    return datetime.now(_STATS_TZ).date().isoformat()


def digest_hour_reached(*, hour: int | None = None) -> bool:
    from on1y.config import get_settings

    h = int(hour if hour is not None else get_settings().evening_digest_hour)
    return datetime.now(_STATS_TZ).hour >= h


def evening_digest_path(user_id: int, day: str) -> Path:
    root = user_dir(user_id) / "evening_digests"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{day}.json"


def load_evening_digest(user_id: int, day: str) -> dict[str, Any] | None:
    path = evening_digest_path(user_id, day)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        logger.warning("Invalid evening digest file: %s", path)
        return None


def save_evening_digest(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    day = str(payload.get("digest_date") or "").strip()
    if not day:
        raise ValueError("digest_date required")
    path = evening_digest_path(user_id, day)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def mark_evening_digest_read(user_id: int, day: str) -> dict[str, Any] | None:
    doc = load_evening_digest(user_id, day)
    if doc is None:
        return None
    if not doc.get("read_at"):
        doc["read_at"] = utc_now_iso()
        save_evening_digest(user_id, doc)
    return doc


def _locale_for_user(user_id: int | None = None) -> str:
    profile = load_user_profile(user_id)
    app = profile.get("app") if isinstance(profile.get("app"), dict) else {}
    loc = str(app.get("locale") or "zh").strip().lower()
    return "en" if loc.startswith("en") else "zh"


def _meta_dt_local(meta_key: str, meta: dict[str, Any]) -> date | None:
    raw = meta.get(meta_key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_STATS_TZ).date()


def _updated_local(updated_at: str | None) -> date | None:
    dt = _parse_ingested_dt(updated_at)
    if dt is None:
        return None
    return dt.astimezone(_STATS_TZ).date()


def _parse_day(day: str) -> date:
    try:
        return date.fromisoformat(day.strip())
    except ValueError as exc:
        raise ValueError(f"invalid date: {day}") from exc


def _count_unread_feed(storage: Any) -> int:
    conn = storage._connect()
    user_clause, user_params = storage._user_scope_parts(conn)
    user_filter = f" AND {user_clause}" if user_clause else ""
    from on1y.knowledge.read_state import unread_sql

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM raw_items r
        WHERE (r.deleted_at IS NULL OR r.deleted_at = '')
          AND r.extract_status IN ('ok', 'partial')
          AND {is_feed_row_sql("r")}
          AND {unread_sql("r")}
          {user_filter}
        """,
        user_params,
    ).fetchone()
    return int(row["c"] if row else 0)


def _fetch_rows_for_digest(storage: Any) -> list[dict[str, Any]]:
    conn = storage._connect()
    user_clause, user_params = storage._user_scope_parts(conn)
    user_filter = f" AND {user_clause}" if user_clause else ""
    rows = conn.execute(
        f"""
        SELECT
            r.id,
            r.raw_title,
            r.url,
            r.platform,
            r.content_type,
            r.source_meta,
            r.ingested_at,
            r.updated_at,
            r.theme_id,
            th.slug AS theme_slug,
            th.name_zh AS theme_name_zh,
            th.name_en AS theme_name_en,
            d.summary AS distilled_summary
        FROM raw_items r
        LEFT JOIN themes th ON th.id = r.theme_id
        LEFT JOIN distilled_items d ON d.raw_id = r.id AND d.distill_status = 'ok'
        WHERE (r.deleted_at IS NULL OR r.deleted_at = '')
          AND r.extract_status IN ('ok', 'partial')
          AND {is_feed_row_sql("r")}
          {user_filter}
        """,
        user_params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = loads_meta(row["source_meta"])
        out.append(
            {
                "raw_id": int(row["id"]),
                "title": str(row["raw_title"] or row["url"] or "").strip(),
                "platform": str(row["platform"] or "unknown"),
                "content_kind": _content_kind(row["content_type"]),
                "meta": meta,
                "ingested_at": row["ingested_at"],
                "updated_at": row["updated_at"],
                "theme_slug": str(row["theme_slug"] or "other"),
                "theme_name_zh": str(row["theme_name_zh"] or ""),
                "theme_name_en": str(row["theme_name_en"] or ""),
                "summary": str(row["distilled_summary"] or "").strip(),
                "is_read": is_read_meta(meta),
            }
        )
    return out


def aggregate_evening_stats(storage: Any, *, day: str) -> dict[str, Any]:
    target = _parse_day(day)
    published_total = 0
    marked_read = 0
    notes_saved = 0
    by_platform: dict[str, int] = defaultdict(int)
    by_theme: dict[str, dict[str, Any]] = {}
    highlights: list[dict[str, Any]] = []

    for row in _fetch_rows_for_digest(storage):
        meta = row["meta"]
        eff_day = _effective_date(meta, row["ingested_at"])
        if eff_day == target:
            published_total += 1
            by_platform[row["platform"]] += 1
            slug = row["theme_slug"]
            if slug not in by_theme:
                by_theme[slug] = {
                    "slug": slug,
                    "name_zh": row["theme_name_zh"],
                    "name_en": row["theme_name_en"],
                    "count": 0,
                }
            by_theme[slug]["count"] += 1
            highlights.append(
                {
                    "raw_id": row["raw_id"],
                    "title": row["title"],
                    "platform": row["platform"],
                    "summary": row["summary"][:280] if row["summary"] else "",
                    "is_read": row["is_read"],
                }
            )

        read_day = _meta_dt_local("read_at", meta)
        if read_day == target:
            marked_read += 1

        if has_user_note(meta):
            note_day = _updated_local(row["updated_at"])
            if note_day == target:
                notes_saved += 1

    highlights.sort(key=lambda x: (x["is_read"], -len(x.get("summary") or "")))
    highlights = highlights[:8]

    return {
        "digest_date": target.isoformat(),
        "published_total": published_total,
        "marked_read": marked_read,
        "notes_saved": notes_saved,
        "unread_total": _count_unread_feed(storage),
        "by_platform": sorted(
            [{"platform": k, "count": v} for k, v in by_platform.items()],
            key=lambda x: (-x["count"], x["platform"]),
        ),
        "by_theme": sorted(by_theme.values(), key=lambda x: (-x["count"], x["slug"]))[:10],
        "highlights": highlights,
    }


def _evening_system_prompt(locale: str) -> str:
    if locale == "en":
        return (
            "You are the editor of a personal knowledge evening digest. "
            "Write a concise, warm briefing (2–4 short paragraphs) in English. "
            "Cover what arrived today, reading progress, notes, themes, and what is still unread. "
            "No markdown headings; plain paragraphs only."
        )
    return (
        "你是个人知识库的晚报编辑。"
        "用中文写一段简洁、有温度的晚间简报（2–4 个短段）。"
        "涵盖今日新内容、阅读进度、笔记、主题分布，以及仍未读的内容。"
        "不要用 Markdown 标题，只用纯文本段落。"
    )


def _evening_user_prompt(stats: dict[str, Any], locale: str) -> str:
    lines = [
        f"date: {stats['digest_date']}",
        f"published_today: {stats['published_total']}",
        f"marked_read_today: {stats['marked_read']}",
        f"notes_saved_today: {stats['notes_saved']}",
        f"unread_in_library: {stats['unread_total']}",
        f"by_platform: {stats['by_platform']}",
        f"by_theme: {stats['by_theme']}",
        "highlights:",
    ]
    for item in stats.get("highlights") or []:
        lines.append(
            f"- [{item['platform']}] {item['title']} "
            f"(read={item['is_read']}) {item.get('summary') or ''}"
        )
    if locale == "en":
        lines.insert(0, "Summarize the following stats for the user's evening digest:")
    else:
        lines.insert(0, "请根据以下统计数据撰写晚报正文：")
    return "\n".join(lines)


def generate_evening_llm_summary(
    stats: dict[str, Any],
    *,
    locale: str,
) -> tuple[str | None, str | None]:
    from on1y.llm.client import get_llm_client
    from on1y.llm.settings import resolve_llm_settings

    llm = resolve_llm_settings()
    if not llm.api_key_set:
        return None, "llm_not_configured"

    from on1y.config import get_settings

    settings = get_settings()
    try:
        client = get_llm_client()
        text = client.chat(
            _evening_system_prompt(locale),
            _evening_user_prompt(stats, locale),
            max_tokens=min(settings.llm_max_output_tokens, 900),
        )
        summary = (text or "").strip()
        return summary or None, None
    except Exception as exc:
        logger.warning("Evening digest LLM failed: %s", exc)
        return None, str(exc)


def build_evening_digest(
    storage: Any,
    *,
    day: str | None = None,
    force: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    from on1y.auth.context import get_effective_user_id

    uid = user_id if user_id is not None else get_effective_user_id()
    if day is None:
        day = datetime.now(_STATS_TZ).date().isoformat()
    else:
        _parse_day(day)

    if not force:
        existing = load_evening_digest(uid, day)
        if existing is not None:
            return existing

    locale = _locale_for_user(uid)
    stats = aggregate_evening_stats(storage, day=day)
    llm_summary, llm_error = generate_evening_llm_summary(stats, locale=locale)

    payload: dict[str, Any] = {
        "digest_date": day,
        "generated_at": utc_now_iso(),
        "locale": locale,
        "timezone": "Asia/Shanghai",
        "stats": stats,
        "llm_summary": llm_summary,
        "llm_error": llm_error,
        "read_at": None,
    }
    return save_evening_digest(uid, payload)


def list_evening_digest_dates(user_id: int, *, limit: int = 14) -> list[str]:
    root = user_dir(user_id) / "evening_digests"
    if not root.is_dir():
        return []
    days = sorted((p.stem for p in root.glob("*.json")), reverse=True)
    return days[:limit]


def evening_digest_status(user_id: int) -> dict[str, Any]:
    from on1y.config import get_settings

    today = today_digest_date()
    hour = int(get_settings().evening_digest_hour)
    doc = load_evening_digest(user_id, today)
    history = list_evening_digest_dates(user_id, limit=60)
    return {
        "today": today,
        "digest_hour": hour,
        "timezone": "Asia/Shanghai",
        "hour_reached": digest_hour_reached(hour=hour),
        "today_available": doc is not None,
        "today_unread": doc is not None and not bool(doc.get("read_at")),
        "generated_at": doc.get("generated_at") if doc else None,
        "history_dates": history,
    }


def latest_evening_digest_status(user_id: int) -> dict[str, Any]:
    """Backward-compatible alias focused on today's digest."""
    view = evening_digest_status(user_id)
    return {
        "available": view["today_available"],
        "unread": view["today_unread"],
        "digest_date": view["today"] if view["today_available"] else None,
        "generated_at": view.get("generated_at"),
        **view,
    }


def public_evening_digest_view(doc: dict[str, Any]) -> dict[str, Any]:
    stats = doc.get("stats") if isinstance(doc.get("stats"), dict) else {}
    return {
        "digest_date": doc.get("digest_date"),
        "generated_at": doc.get("generated_at"),
        "locale": doc.get("locale"),
        "timezone": doc.get("timezone"),
        "read_at": doc.get("read_at"),
        "llm_summary": doc.get("llm_summary"),
        "llm_error": doc.get("llm_error"),
        "stats": stats,
        "unread": not bool(doc.get("read_at")),
    }
