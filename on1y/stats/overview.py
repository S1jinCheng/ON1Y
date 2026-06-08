"""Aggregate feed statistics from raw_items (excludes hotlist)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from on1y.hotlist.sql import is_feed_row_sql
from on1y.stats.timezone_util import stats_timezone

_STATS_TZ = stats_timezone()
_WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_WEEKDAY_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
from on1y.utils.json_util import loads_meta
from on1y.utils.published_at import published_at_from_meta


def _parse_ingested_dt(ingested_at: str | None) -> datetime | None:
    if not ingested_at:
        return None
    text = str(ingested_at).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                parsed = datetime.strptime(text[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _effective_datetime(meta: dict[str, Any], ingested_at: str | None) -> datetime | None:
    dt = published_at_from_meta(meta)
    if dt is None:
        dt = _parse_ingested_dt(ingested_at)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_STATS_TZ)


def _effective_date(meta: dict[str, Any], ingested_at: str | None) -> date | None:
    dt = _effective_datetime(meta, ingested_at)
    return dt.date() if dt is not None else None


def _content_kind(content_type: str | None) -> str:
    key = (content_type or "unknown").strip().lower()
    if key == "video":
        return "video"
    if key == "article":
        return "text"
    return "unknown"


def _fetch_feed_rows(storage: Any) -> list[dict[str, Any]]:
    conn = storage._connect()
    user_clause, user_params = storage._user_scope_parts(conn)
    user_filter = f" AND {user_clause}" if user_clause else ""
    rows = conn.execute(
        f"""
        SELECT
            r.platform,
            r.content_type,
            r.source_meta,
            r.ingested_at,
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
                "platform": str(row["platform"] or "unknown"),
                "content_type": str(row["content_type"] or "unknown"),
                "content_kind": _content_kind(row["content_type"]),
                "meta": meta,
                "ingested_at": row["ingested_at"],
                "theme_id": int(row["theme_id"]) if row["theme_id"] is not None else None,
                "theme_slug": str(row["theme_slug"] or "other"),
                "theme_name_zh": str(row["theme_name_zh"] or ""),
                "theme_name_en": str(row["theme_name_en"] or ""),
            }
        )
    return out


def build_stats_overview(storage: Any, *, days: int = 90) -> dict[str, Any]:
    days = max(7, min(int(days), 366))
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)

    rows = _fetch_feed_rows(storage)
    with_published = 0
    by_platform: dict[str, int] = defaultdict(int)
    by_content_kind: dict[str, int] = defaultdict(int)
    by_theme: dict[str, dict[str, Any]] = {}
    timeline: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_hour: dict[int, int] = defaultdict(int)
    by_weekday: dict[int, int] = defaultdict(int)

    for row in rows:
        meta = row["meta"]
        platform = row["platform"]
        kind = row["content_kind"]
        by_platform[platform] += 1
        by_content_kind[kind] += 1

        if published_at_from_meta(meta) is not None:
            with_published += 1

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

        eff_dt = _effective_datetime(meta, row["ingested_at"])
        if eff_dt is not None and start <= eff_dt.date() <= today:
            day_key = eff_dt.date().isoformat()
            timeline[day_key][platform] += 1
            timeline[day_key]["_total"] += 1
            by_hour[int(eff_dt.hour)] += 1
            by_weekday[int(eff_dt.weekday())] += 1

    timeline_list: list[dict[str, Any]] = []
    cursor = start
    while cursor <= today:
        key = cursor.isoformat()
        plat = {k: v for k, v in timeline[key].items() if k != "_total"}
        timeline_list.append(
            {
                "date": key,
                "total": int(timeline[key].get("_total", 0)),
                "by_platform": plat,
            }
        )
        cursor += timedelta(days=1)

    platform_rows = sorted(
        [{"platform": k, "count": v} for k, v in by_platform.items()],
        key=lambda x: (-x["count"], x["platform"]),
    )
    kind_rows = sorted(
        [{"content_kind": k, "count": v} for k, v in by_content_kind.items()],
        key=lambda x: (-x["count"], x["content_kind"]),
    )
    theme_rows = sorted(by_theme.values(), key=lambda x: (-x["count"], x["slug"]))

    hour_rows = [
        {"hour": h, "count": int(by_hour.get(h, 0))}
        for h in range(24)
    ]
    weekday_rows = [
        {
            "weekday": wd,
            "label_zh": _WEEKDAY_ZH[wd],
            "label_en": _WEEKDAY_EN[wd],
            "count": int(by_weekday.get(wd, 0)),
        }
        for wd in range(7)
    ]
    timeline_peaks = sorted(
        [{"date": d["date"], "total": d["total"]} for d in timeline_list if d["total"] > 0],
        key=lambda x: (-x["total"], x["date"]),
    )[:10]

    peak_hour = max(hour_rows, key=lambda x: x["count"]) if hour_rows else None
    peak_weekday = max(weekday_rows, key=lambda x: x["count"]) if weekday_rows else None

    return {
        "days": days,
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date_basis": "published_at_with_ingested_fallback",
        "timezone": "Asia/Shanghai",
        "totals": {
            "items": len(rows),
            "with_original_publish_time": with_published,
            "in_range": sum(d["total"] for d in timeline_list),
        },
        "by_platform": platform_rows,
        "by_content_kind": kind_rows,
        "by_theme": theme_rows,
        "timeline": timeline_list,
        "by_hour": hour_rows,
        "by_weekday": weekday_rows,
        "timeline_peaks": timeline_peaks,
        "highlights": {
            "peak_hour": peak_hour["hour"] if peak_hour and peak_hour["count"] else None,
            "peak_hour_count": peak_hour["count"] if peak_hour else 0,
            "peak_weekday": peak_weekday["weekday"] if peak_weekday and peak_weekday["count"] else None,
            "peak_weekday_count": peak_weekday["count"] if peak_weekday else 0,
            "busiest_day": timeline_peaks[0]["date"] if timeline_peaks else None,
            "busiest_day_count": timeline_peaks[0]["total"] if timeline_peaks else 0,
        },
    }


def build_daily_digest(storage: Any, *, day: str) -> dict[str, Any]:
    """Items whose effective publish day matches `day` (ISO date) — for future daily reports."""
    try:
        target = date.fromisoformat(day.strip())
    except ValueError as exc:
        raise ValueError(f"invalid date: {day}") from exc

    rows = _fetch_feed_rows(storage)
    matched: list[dict[str, Any]] = []
    by_platform: dict[str, int] = defaultdict(int)
    by_content_kind: dict[str, int] = defaultdict(int)

    for row in rows:
        eff = _effective_date(row["meta"], row["ingested_at"])
        if eff != target:
            continue
        platform = row["platform"]
        kind = row["content_kind"]
        by_platform[platform] += 1
        by_content_kind[kind] += 1
        matched.append(
            {
                "platform": platform,
                "content_kind": kind,
                "content_type": row["content_type"],
            }
        )

    return {
        "date": target.isoformat(),
        "total": len(matched),
        "by_platform": dict(by_platform),
        "by_content_kind": dict(by_content_kind),
        "date_basis": "published_at_with_ingested_fallback",
    }
