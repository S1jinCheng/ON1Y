"""Evening digest: daily stats + optional LLM narrative summary."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from on1y.distill.prompts import (
    EVENING_DIGEST_PROMPT_VERSION,
    build_evening_digest_system_prompt,
    build_evening_digest_user_prompt,
)
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
_FOCUS_DOMAIN_ALIAS: dict[str, str] = {
    "economy": "economics",
    "economics": "economics",
    "经济": "economics",
    "finance": "economics",
    "fintech": "economics",
    "politics": "news",
    "policy": "news",
    "public-affairs": "news",
    "public_affairs": "news",
    "时政": "news",
    "news": "news",
    "technology": "technology",
    "tech": "technology",
    "科技": "technology",
    "ai": "technology",
}
_THEME_WEIGHT: dict[str, int] = {
    "news": 24,
    "economics": 22,
    "technology": 22,
    "research": 14,
    "other": 6,
}
_PLATFORM_WEIGHT: dict[str, int] = {
    "twitter": 20,
    "x": 20,
    "zhihu": 18,
    "economist": 18,
    "youtube": 12,
    "bilibili": 10,
}


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
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(_STATS_TZ).date()


def _updated_local(updated_at: str | None) -> date | None:
    dt = _parse_ingested_dt(updated_at)
    if dt is None:
        return None
    return dt.astimezone(_STATS_TZ).date()


def _meta_datetime_local(meta: dict[str, Any]) -> datetime | None:
    for key in ("published", "published_at", "upload_date", "updated_at", "created_at"):
        raw = meta.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(_STATS_TZ)
    return None


def _normalize_focus_token(value: str) -> str:
    token = re.sub(r"[\s\-_]+", "", value.strip().casefold())
    return token


def _resolve_focus_slug(token: str) -> str:
    if not token:
        return ""
    return _FOCUS_DOMAIN_ALIAS.get(token, token)


def _focus_slugs_from_settings() -> set[str]:
    from on1y.config import get_settings

    raw = str(get_settings().evening_digest_focus_domains or "")
    tokens = [_normalize_focus_token(part) for part in raw.split(",")]
    slugs = {_resolve_focus_slug(token) for token in tokens if token}
    return {slug for slug in slugs if slug}


def _item_focus_slug(row: dict[str, Any]) -> str:
    candidates = [
        _normalize_focus_token(str(row.get("theme_slug") or "")),
        _normalize_focus_token(str(row.get("theme_name_zh") or "")),
        _normalize_focus_token(str(row.get("theme_name_en") or "")),
    ]
    for token in candidates:
        resolved = _resolve_focus_slug(token)
        if resolved:
            return resolved
    return "other"


def _title_fingerprint(title: str) -> str:
    base = re.sub(r"\W+", "", title.casefold(), flags=re.UNICODE)
    return base[:48]


def _timeliness_score(
    *,
    target: date,
    meta: dict[str, Any],
    ingested_at: str | None,
) -> int:
    score = 50
    published_local = _meta_datetime_local(meta)
    if published_local is not None:
        target_end = datetime.combine(target, time.max, tzinfo=_STATS_TZ)
        age_hours = max(0.0, (target_end - published_local).total_seconds() / 3600.0)
        score += max(8, 36 - int(age_hours * 1.2))
    else:
        ingested_dt = _parse_ingested_dt(ingested_at)
        if ingested_dt is not None and ingested_dt.astimezone(_STATS_TZ).date() == target:
            score += 20
        else:
            score += 10
    return score


def _impact_score(*, row: dict[str, Any], title_platform_count: int) -> int:
    theme_weight = _THEME_WEIGHT.get(_item_focus_slug(row), 10)
    platform_weight = _PLATFORM_WEIGHT.get(str(row.get("platform") or "").lower(), 8)
    spread_bonus = 12 if title_platform_count >= 2 else 0
    return theme_weight + platform_weight + spread_bonus


def _pick_image_url(meta: dict[str, Any]) -> str:
    candidates: list[Any] = [
        meta.get("image_url"),
        meta.get("cover_url"),
        meta.get("thumbnail"),
        meta.get("thumbnail_url"),
        meta.get("poster"),
        meta.get("image"),
    ]
    media = meta.get("media")
    if isinstance(media, list):
        for item in media[:5]:
            if isinstance(item, dict):
                candidates.append(item.get("url"))
                candidates.append(item.get("image_url"))
    for value in candidates:
        if not value:
            continue
        url = str(value).strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
    return ""


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
                "url": str(row["url"] or "").strip(),
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
    from on1y.config import get_settings

    target = _parse_day(day)
    settings = get_settings()
    published_total = 0
    marked_read = 0
    notes_saved = 0
    by_platform: dict[str, int] = defaultdict(int)
    by_theme: dict[str, dict[str, Any]] = {}
    highlight_candidates: list[dict[str, Any]] = []
    focus_slugs = _focus_slugs_from_settings()

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
            highlight_candidates.append(
                {
                    "raw_id": row["raw_id"],
                    "title": row["title"],
                    "url": row.get("url") or "",
                    "platform": row["platform"],
                    "summary": row["summary"][:280] if row["summary"] else "",
                    "is_read": row["is_read"],
                    "theme_slug": row["theme_slug"],
                    "theme_name_zh": row["theme_name_zh"],
                    "theme_name_en": row["theme_name_en"],
                    "image_url": _pick_image_url(meta),
                    "meta": meta,
                    "ingested_at": row["ingested_at"],
                }
            )

        read_day = _meta_dt_local("read_at", meta)
        if read_day == target:
            marked_read += 1

        if has_user_note(meta):
            note_day = _updated_local(row["updated_at"])
            if note_day == target:
                notes_saved += 1

    title_platforms: dict[str, set[str]] = defaultdict(set)
    for item in highlight_candidates:
        key = _title_fingerprint(item.get("title") or "")
        if key:
            title_platforms[key].add(str(item.get("platform") or "unknown"))

    for item in highlight_candidates:
        fingerprint = _title_fingerprint(item.get("title") or "")
        spread = len(title_platforms.get(fingerprint) or ())
        timeliness = _timeliness_score(
            target=target,
            meta=item.get("meta") or {},
            ingested_at=item.get("ingested_at"),
        )
        impact = _impact_score(row=item, title_platform_count=spread)
        summary_bonus = min(6, len(item.get("summary") or "") // 60)
        unread_bonus = 8 if not item.get("is_read") else 0
        item["timeliness_score"] = timeliness
        item["impact_score"] = impact
        item["score"] = timeliness + impact + summary_bonus + unread_bonus
        item["focus_slug"] = _item_focus_slug(item)
        item["is_focus"] = item["focus_slug"] in focus_slugs

    highlight_candidates.sort(
        key=lambda x: (-int(x.get("score") or 0), x["is_read"], x.get("title") or "")
    )

    max_crux = int(settings.evening_digest_max_crux)
    focus_quota = max(1, round(max_crux * 0.6))
    focus_rows = [row for row in highlight_candidates if row.get("is_focus")]
    non_focus_rows = [row for row in highlight_candidates if not row.get("is_focus")]
    selected: list[dict[str, Any]] = focus_rows[:focus_quota]
    if len(selected) < max_crux:
        selected.extend(non_focus_rows[: max_crux - len(selected)])
    if len(selected) < max_crux:
        selected.extend(
            row for row in highlight_candidates if row not in selected
        )
        selected = selected[:max_crux]

    highlights = [
        {
            "raw_id": item["raw_id"],
            "title": item["title"],
            "url": item.get("url") or "",
            "platform": item["platform"],
            "summary": item["summary"],
            "is_read": item["is_read"],
            "theme_slug": item["theme_slug"],
            "score": int(item.get("score") or 0),
            "timeliness_score": int(item.get("timeliness_score") or 0),
            "impact_score": int(item.get("impact_score") or 0),
            "image_url": item.get("image_url") or "",
        }
        for item in selected
    ]

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
        "selection_meta": {
            "prompt_version": EVENING_DIGEST_PROMPT_VERSION,
            "focus_slugs": sorted(focus_slugs),
            "candidate_count": len(highlight_candidates),
            "focus_candidate_count": len(focus_rows),
            "selected_count": len(highlights),
            "focus_quota": focus_quota,
            "focus_selected_count": sum(
                1 for item in highlights if item["theme_slug"] in focus_slugs
            ),
            "focus_backfill": len(focus_rows) < focus_quota,
        },
    }


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
        max_tokens = max(int(settings.llm_max_output_tokens), 900)
        text = client.chat(
            build_evening_digest_system_prompt(
                locale=locale,
                max_crux=int(settings.evening_digest_max_crux),
                max_chars=int(settings.evening_digest_max_chars),
            ),
            build_evening_digest_user_prompt(stats=stats, locale=locale),
            max_tokens=max_tokens,
        )
        summary = (text or "").strip()
        return summary or None, None
    except Exception as exc:
        if "empty content" in str(exc).lower():
            try:
                # Retry once with a higher token budget for longer markdown output.
                retry_text = client.chat(
                    build_evening_digest_system_prompt(
                        locale=locale,
                        max_crux=int(settings.evening_digest_max_crux),
                        max_chars=int(settings.evening_digest_max_chars),
                    ),
                    build_evening_digest_user_prompt(stats=stats, locale=locale),
                    max_tokens=max(max_tokens, 1400),
                )
                retry_summary = (retry_text or "").strip()
                if retry_summary:
                    return retry_summary, None
            except Exception as retry_exc:
                logger.warning("Evening digest LLM retry failed: %s", retry_exc)
                return None, str(retry_exc)
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
        "prompt_version": EVENING_DIGEST_PROMPT_VERSION,
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
        "prompt_version": doc.get("prompt_version"),
        "locale": doc.get("locale"),
        "timezone": doc.get("timezone"),
        "read_at": doc.get("read_at"),
        "llm_summary": doc.get("llm_summary"),
        "llm_error": doc.get("llm_error"),
        "stats": stats,
        "unread": not bool(doc.get("read_at")),
    }
