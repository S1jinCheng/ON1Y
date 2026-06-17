"""Feed filtering by effective local publish calendar day."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from on1y.stats.overview import _effective_datetime
from on1y.stats.timezone_util import stats_timezone
from on1y.utils.json_util import loads_meta


def local_today() -> date:
    return datetime.now(stats_timezone()).date()


def parse_feed_date(day: str) -> date:
    try:
        return date.fromisoformat(str(day).strip())
    except ValueError as exc:
        raise ValueError(f"invalid feed_date: {day}") from exc


def effective_publish_local_day_sql(alias: str = "r") -> str:
    """SQLite expression: local publish day (Asia/Shanghai) from source_meta or ingested_at."""
    meta = f"{alias}.source_meta"
    ing = f"{alias}.ingested_at"
    published = f"json_extract({meta}, '$.published')"
    published_at = f"json_extract({meta}, '$.published_at')"
    entry_published = f"json_extract({meta}, '$.entry_published')"
    return f"""COALESCE(
        CASE WHEN typeof({published}) = 'integer'
            THEN date(datetime({published}, 'unixepoch'), '+8 hours') END,
        CASE WHEN typeof({published}) = 'text' AND length({published}) >= 19
            THEN date({published}, '+8 hours') END,
        CASE WHEN typeof({published}) = 'text' AND length({published}) = 10
            THEN date({published}) END,
        CASE WHEN typeof({published_at}) = 'text' AND length({published_at}) >= 10
            THEN date({published_at}, '+8 hours') END,
        CASE WHEN typeof({entry_published}) = 'text' AND length({entry_published}) >= 10
            THEN date({entry_published}, '+8 hours') END,
        date({ing}, '+8 hours')
    )"""


def feed_date_where_clause(day: str, *, alias: str = "r") -> tuple[str, list[Any]]:
    parse_feed_date(day)
    expr = effective_publish_local_day_sql(alias)
    return f"({expr}) = ?", [day]


def item_matches_feed_date(item: dict[str, Any], day: str) -> bool:
    target = parse_feed_date(day)
    meta: dict[str, Any] = {}
    if item.get("published_at"):
        meta["published"] = item["published_at"]
    dt = _effective_datetime(meta, item.get("ingested_at"))
    if dt is None:
        return False
    return dt.astimezone(stats_timezone()).date() == target


def meta_matches_feed_date(source_meta: str | None, ingested_at: str | None, day: str) -> bool:
    meta = loads_meta(source_meta)
    dt = _effective_datetime(meta, ingested_at)
    if dt is None:
        return False
    return dt.astimezone(stats_timezone()).date() == parse_feed_date(day)
