"""Per-user sync tuning stored in data/users/<id>/sync_settings.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from on1y.auth.context import get_effective_user_id
from on1y.config import Settings, get_settings

logger = logging.getLogger(__name__)

_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "zhihu_api_poll_max_followees": (1, 200),
    "zhihu_api_poll_max_pages": (1, 20),
    "zhihu_api_poll_backfill_pages": (1, 50),
    "auto_sync_interval_minutes": (5, 24 * 60),
    "auto_sync_pipeline_batch_size": (5, 100),
    "collections_sync_interval_seconds": (30, 3600),
    "bilibili_up_poll_max_ups_per_run": (0, 200),
    "bilibili_dynamic_poll_max_pages": (1, 50),
    "bilibili_dynamic_poll_backfill_max_pages": (1, 100),
    "rss_backfill_max_items_per_feed": (1, 500),
    "cold_start_bilibili_dynamic_days": (1, 30),
    "cold_start_bilibili_dynamic_max_pages": (1, 200),
    "economist_auto_sync_interval_minutes": (15, 24 * 60),
}

_FLOAT_BOUNDS: dict[str, tuple[float, float]] = {
    "bilibili_up_poll_rate_limit_backoff_seconds": (5.0, 600.0),
    "bilibili_up_poll_rate_limit_cooldown_seconds": (0.0, 600.0),
    "alert_cooldown_seconds": (60.0, 3600.0),
}

_BOOL_KEYS = frozenset(
    {
        "youtube_auto_refresh_channels",
        "auto_sync_enabled",
        "collections_sync_enabled",
        "zhihu_auto_refresh_follows",
        "economist_auto_sync_enabled",
        "alert_enabled",
    }
)

_STR_KEYS = frozenset(
    {
        "zhihu_follow_sync_mode",
        "zhihu_rsshub_base",
        "bilibili_up_poll_mode",
        "economist_github_raw_base",
        "alert_webhook_url",
    }
)

EFFECTIVE_KEYS: tuple[str, ...] = (
    "zhihu_api_poll_max_followees",
    "zhihu_api_poll_max_pages",
    "zhihu_api_poll_backfill_pages",
    "zhihu_follow_sync_mode",
    "zhihu_rsshub_base",
    "youtube_auto_refresh_channels",
    "zhihu_auto_refresh_follows",
    "auto_sync_enabled",
    "auto_sync_interval_minutes",
    "auto_sync_pipeline_batch_size",
    "collections_sync_enabled",
    "collections_sync_interval_seconds",
    "bilibili_up_poll_mode",
    "bilibili_up_poll_max_ups_per_run",
    "bilibili_dynamic_poll_max_pages",
    "bilibili_dynamic_poll_backfill_max_pages",
    "bilibili_up_poll_rate_limit_backoff_seconds",
    "bilibili_up_poll_rate_limit_cooldown_seconds",
    "rss_backfill_max_items_per_feed",
    "cold_start_bilibili_dynamic_days",
    "cold_start_bilibili_dynamic_max_pages",
    "economist_auto_sync_enabled",
    "economist_auto_sync_interval_minutes",
    "economist_github_raw_base",
    "alert_enabled",
    "alert_cooldown_seconds",
    "alert_webhook_url",
)


def settings_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    from on1y.user.paths import user_dir

    return user_dir(uid) / "sync_settings.json"


def _empty_payload() -> dict[str, Any]:
    return {}


def load_sync_prefs(*, user_id: int | None = None) -> dict[str, Any]:
    path = settings_file_path(user_id=user_id)
    if not path.is_file():
        return _empty_payload()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _empty_payload()
    except json.JSONDecodeError:
        logger.warning("Invalid sync settings file: %s", path)
        return _empty_payload()


def _clamp_int(key: str, value: int) -> int:
    lo, hi = _INT_BOUNDS[key]
    return max(lo, min(hi, value))


def _clamp_float(key: str, value: float) -> float:
    lo, hi = _FLOAT_BOUNDS[key]
    return max(lo, min(hi, value))


def save_sync_settings(*, user_id: int | None = None, **fields: Any) -> dict[str, Any]:
    uid = user_id if user_id is not None else get_effective_user_id()
    current = load_sync_prefs(user_id=uid)

    for key, raw in fields.items():
        if raw is None:
            continue
        if key in _BOOL_KEYS:
            current[key] = bool(raw)
        elif key in _INT_BOUNDS:
            current[key] = _clamp_int(key, int(raw))
        elif key in _FLOAT_BOUNDS:
            current[key] = _clamp_float(key, float(raw))
        elif key == "zhihu_follow_sync_mode":
            mode = str(raw).strip().lower()
            if mode in {"api", "rss"}:
                current[key] = mode
        elif key == "bilibili_up_poll_mode":
            mode = str(raw).strip().lower()
            if mode in {"dynamic", "space"}:
                current[key] = mode
        elif key in _STR_KEYS:
            text = str(raw or "").strip().rstrip("/")
            if text:
                current[key] = text
            else:
                current.pop(key, None)

    path = settings_file_path(user_id=uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    get_settings.cache_clear()
    return current


def _effective_value(key: str, prefs: dict[str, Any], base: Settings) -> Any:
    if key in prefs:
        return prefs[key]
    return getattr(base, key)


def public_settings_view(*, user_id: int | None = None) -> dict[str, Any]:
    base = get_settings()
    prefs = load_sync_prefs(user_id=user_id)
    out: dict[str, Any] = {
        "defaults": {key: getattr(base, key) for key in EFFECTIVE_KEYS},
        "user_overrides": prefs,
    }
    for key in EFFECTIVE_KEYS:
        out[key] = _effective_value(key, prefs, base)
    out["zhihu_follow_sync_mode"] = str(out["zhihu_follow_sync_mode"]).lower()
    out["bilibili_up_poll_mode"] = str(out["bilibili_up_poll_mode"]).lower()
    return out


def apply_to_settings(settings: Settings, *, user_id: int | None = None) -> Settings:
    prefs = load_sync_prefs(user_id=user_id)
    if not prefs:
        return settings
    updates: dict[str, Any] = {key: prefs[key] for key in EFFECTIVE_KEYS if key in prefs}
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def resolve_settings(*, user_id: int | None = None) -> Settings:
    uid = user_id if user_id is not None else get_effective_user_id()
    return apply_to_settings(get_settings(), user_id=uid)


def any_auto_sync_enabled() -> bool:
    base = get_settings()
    if base.auto_sync_enabled:
        return True
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import list_sync_user_ids

    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage)
    finally:
        storage.close()
    return any(resolve_settings(user_id=uid).auto_sync_enabled for uid in user_ids)


def any_collections_sync_enabled() -> bool:
    base = get_settings()
    if base.collections_sync_enabled:
        return True
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import list_sync_user_ids

    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage)
    finally:
        storage.close()
    return any(resolve_settings(user_id=uid).collections_sync_enabled for uid in user_ids)


def any_economist_auto_sync_enabled() -> bool:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.user.accounts import list_sync_user_ids
    from on1y.user.profile import load_user_profile

    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage)
    finally:
        storage.close()
    for uid in user_ids:
        with user_context(uid):
            if not resolve_settings(user_id=uid).economist_auto_sync_enabled:
                continue
            if load_user_profile(uid)["economist"]["auto_ingest_enabled"]:
                return True
    return False


def min_economist_sync_interval_minutes() -> int:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.user.accounts import list_sync_user_ids
    from on1y.user.profile import load_user_profile

    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage)
    finally:
        storage.close()
    intervals: list[int] = []
    for uid in user_ids:
        with user_context(uid):
            if not resolve_settings(user_id=uid).economist_auto_sync_enabled:
                continue
            if not load_user_profile(uid)["economist"]["auto_ingest_enabled"]:
                continue
            intervals.append(resolve_settings(user_id=uid).economist_auto_sync_interval_minutes)
    return max(15, min(intervals)) if intervals else 60
