"""Weekly reading / notes / theme digest."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from on1y.hotlist.sql import is_feed_row_sql
from on1y.knowledge.notes import has_user_note, note_html_from_meta
from on1y.stats.overview import _content_kind, _effective_date, _parse_ingested_dt
from on1y.stats.timezone_util import stats_timezone
from on1y.utils.html_text import html_to_plain_text
from on1y.utils.json_util import loads_meta

_STATS_TZ = stats_timezone()


def week_range_containing(day: date) -> tuple[date, date]:
    """Monday–Sunday week in local stats calendar containing ``day``."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def week_range_for_offset(week_offset: int = 0) -> tuple[date, date]:
    """``week_offset=0`` current week; ``-1`` previous week, etc."""
    today = datetime.now(_STATS_TZ).date()
    anchor = today + timedelta(days=7 * int(week_offset))
    return week_range_containing(anchor)


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


def _fetch_feed_rows(storage: Any) -> list[dict[str, Any]]:
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
            th.name_en AS theme_name_en
        FROM raw_items r
        LEFT JOIN themes th ON th.id = r.theme_id
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
                "content_type": str(row["content_type"] or "unknown"),
                "content_kind": _content_kind(row["content_type"]),
                "meta": meta,
                "ingested_at": row["ingested_at"],
                "updated_at": row["updated_at"],
                "theme_id": int(row["theme_id"]) if row["theme_id"] is not None else None,
                "theme_slug": str(row["theme_slug"] or "other"),
                "theme_name_zh": str(row["theme_name_zh"] or ""),
                "theme_name_en": str(row["theme_name_en"] or ""),
            }
        )
    return out


def build_weekly_review(storage: Any, *, week_offset: int = 0) -> dict[str, Any]:
    week_start, week_end = week_range_for_offset(week_offset)
    prev_start, prev_end = week_start - timedelta(days=7), week_end - timedelta(days=7)

    published_total = 0
    marked_read = 0
    notes_updated = 0
    prev_published = 0

    by_platform: dict[str, int] = defaultdict(int)
    by_theme: dict[str, dict[str, Any]] = {}
    daily: dict[str, int] = defaultdict(int)
    note_items: list[dict[str, Any]] = []

    rows = _fetch_feed_rows(storage)
    for row in rows:
        meta = row["meta"]
        eff_day = _effective_date(meta, row["ingested_at"])
        if eff_day is not None and week_start <= eff_day <= week_end:
            published_total += 1
            platform = row["platform"]
            by_platform[platform] += 1
            daily[eff_day.isoformat()] += 1
            slug = row["theme_slug"]
            if slug not in by_theme:
                by_theme[slug] = {
                    "theme_id": row["theme_id"],
                    "slug": slug,
                    "name_zh": row["theme_name_zh"],
                    "name_en": row["theme_name_en"],
                    "count": 0,
                }
            by_theme[slug]["count"] += 1
        if eff_day is not None and prev_start <= eff_day <= prev_end:
            prev_published += 1

        read_day = _meta_dt_local("read_at", meta)
        if read_day is not None and week_start <= read_day <= week_end:
            marked_read += 1

        if has_user_note(meta):
            note_day = _updated_local(row["updated_at"])
            if note_day is not None and week_start <= note_day <= week_end:
                notes_updated += 1
                preview = html_to_plain_text(note_html_from_meta(meta))[:120]
                note_items.append(
                    {
                        "raw_id": row["raw_id"],
                        "title": row["title"],
                        "platform": row["platform"],
                        "note_preview": preview,
                        "updated_at": row["updated_at"],
                    }
                )

    daily_list: list[dict[str, Any]] = []
    cursor = week_start
    while cursor <= week_end:
        key = cursor.isoformat()
        daily_list.append({"date": key, "total": int(daily.get(key, 0))})
        cursor += timedelta(days=1)

    note_items.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)

    return {
        "week_offset": int(week_offset),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": "Asia/Shanghai",
        "date_basis": "published_at_with_ingested_fallback",
        "reading": {
            "published_total": published_total,
            "marked_read": marked_read,
            "by_platform": sorted(
                [{"platform": k, "count": v} for k, v in by_platform.items()],
                key=lambda x: (-x["count"], x["platform"]),
            ),
            "by_theme": sorted(by_theme.values(), key=lambda x: (-x["count"], x["slug"]))[:12],
            "daily": daily_list,
        },
        "notes": {
            "updated_count": notes_updated,
            "items": note_items[:20],
        },
        "comparison": {
            "published_prev_week": prev_published,
            "published_delta": published_total - prev_published,
        },
    }
