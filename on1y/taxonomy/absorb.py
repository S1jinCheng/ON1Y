"""Smart theme absorb: discover related themes, prefilter, and reclassify."""

from __future__ import annotations

import logging
import threading
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.distill.prompts import build_absorb_disambiguation_block
from on1y.llm.client import get_llm_client
from on1y.taxonomy.constants import ABSORB_RELATION_CATCH_ALL, OTHER_THEME_SLUG
from on1y.taxonomy.discover import (
    build_scan_plan,
    discover_related_themes,
    prefilter_candidates,
)
from on1y.taxonomy.remap import build_remap_user_prompt

logger = logging.getLogger(__name__)

_absorb_guard = threading.Lock()
_absorb_running: set[int] = set()
_absorb_pending: dict[int, threading.Timer] = {}


def build_absorb_classify_prompt(
    *,
    locale: str,
    target_theme: dict[str, Any],
    source_theme: dict[str, Any],
    disambiguation: list[dict[str, Any]],
    themes_by_slug: dict[str, dict[str, Any]],
) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    target_slug = str(target_theme["slug"]).lower()
    source_slug = str(source_theme["slug"]).lower()
    if locale.lower().startswith("en"):
        target_name = str(target_theme.get("name_en") or target_slug)
        target_desc = str(target_theme.get("description_en") or "")
        source_name = str(source_theme.get("name_en") or source_slug)
        source_desc = str(source_theme.get("description_en") or "")
    else:
        target_name = str(target_theme.get("name_zh") or target_slug)
        target_desc = str(target_theme.get("description_zh") or "")
        source_name = str(source_theme.get("name_zh") or source_slug)
        source_desc = str(source_theme.get("description_zh") or "")

    option_lines = [
        f'- "{target_slug}": {target_name} — {target_desc} [TARGET: move here only if primarily this topic]',
    ]
    if source_slug != OTHER_THEME_SLUG:
        option_lines.append(
            f'- "{source_slug}": {source_name} — {source_desc} [KEEP: current bucket, no move]',
        )
    option_lines.append(
        f'- "{OTHER_THEME_SLUG}": Other — content that does not primarily belong to the target theme',
    )
    options = "\n".join(option_lines)
    disambiguation_block = build_absorb_disambiguation_block(
        disambiguation,
        theme=target_theme,
        themes_by_slug=themes_by_slug,
        locale=locale,
    )
    return f"""You decide whether content should move into a theme bucket. Respond in {lang} only.

Return ONE JSON object:
{{"theme_slug": "<one slug from the list below>"}}

Candidate themes (pick exactly one):
{options}
{disambiguation_block}
Rules:
- Pick "{target_slug}" only when content PRIMARILY belongs there (dominant topic, not a passing mention).
- If content still fits the current theme "{source_slug}" better, pick "{source_slug}" (no move).
- If uncertain or only loosely related to the target, pick "{source_slug}" when not other, else "{OTHER_THEME_SLUG}".
- Be conservative about moving items out of non-other themes."""


def orchestrate_theme_absorb(
    storage: SqliteStorage,
    *,
    theme_id: int,
    locale: str | None = None,
    forced_source_slugs: list[str] | None = None,
    rediscover: bool = True,
) -> dict[str, Any]:
    """Discover related themes, prefilter candidates, and reclassify into `theme_id`."""
    from on1y.config import get_settings
    from on1y.llm.settings import resolve_llm_settings

    if not resolve_llm_settings().api_key_set:
        return {
            "absorbed": 0,
            "skipped": 0,
            "failed": 0,
            "candidates": 0,
            "reason": "no_llm_key",
        }

    theme = storage.get_theme_by_id(theme_id)
    if theme is None:
        raise ValueError(f"theme not found: {theme_id}")
    if theme.get("archived_at"):
        raise ValueError(f"theme archived: {theme_id}")
    target_slug = str(theme.get("slug") or "").lower()
    if target_slug == OTHER_THEME_SLUG:
        raise ValueError("cannot absorb into built-in other theme")

    settings = get_settings()
    lang = locale or settings.llm_locale
    active = storage.list_active_themes()
    themes_by_slug = {str(row["slug"]).lower(): row for row in active}

    if rediscover or not storage.get_theme_discovery_json(theme_id):
        discovery = discover_related_themes(
            storage,
            theme=theme,
            locale=lang,
            confidence_threshold=settings.absorb_peer_confidence_threshold,
        )
        storage.set_theme_discovery_json(theme_id, discovery)
    else:
        discovery = storage.get_theme_discovery_json(theme_id)

    scan_plan = build_scan_plan(
        discovery,
        themes_by_slug=themes_by_slug,
        forced_source_slugs=forced_source_slugs,
    )
    keywords = list(discovery.get("keywords") or [])
    disambiguation = list(discovery.get("disambiguation") or [])

    client = get_llm_client()
    max_in = settings.llm_distill_max_input_chars
    max_per_source = settings.absorb_max_candidates_per_source

    total_absorbed = 0
    total_skipped = 0
    total_failed = 0
    total_candidates = 0
    per_source_stats: list[dict[str, Any]] = []

    for source_spec in scan_plan:
        source_slug = str(source_spec["slug"]).lower()
        source_theme = themes_by_slug.get(source_slug)
        if source_theme is None:
            continue
        source_id = int(source_theme["id"])
        relation = str(source_spec.get("relation") or "")
        raw_ids = storage.list_raw_ids_by_theme(
            source_id,
            exclude_theme_sources=("user",),
            feed_only=True,
            exclude_deleted=True,
        )
        pool_size = len(raw_ids)
        if relation == ABSORB_RELATION_CATCH_ALL or not source_spec.get("prefilter"):
            candidate_ids = raw_ids
            prefiltered_hits = pool_size
        else:
            candidate_ids, prefiltered_hits = prefilter_candidates(
                storage,
                raw_ids,
                keywords,
                relation=relation,
                max_candidates=max_per_source,
            )

        absorbed = 0
        skipped = 0
        failed = 0
        for raw_id in candidate_ids:
            raw = storage.get_raw_by_id(raw_id)
            if raw is None:
                continue
            detail_tags = storage.get_item_tag_names(raw_id)
            body = (raw.body_text or "").strip()
            if len(body) > max_in:
                body = body[:max_in] + "\n[...truncated...]"
            distilled = storage.get_distilled_by_raw_id(raw_id)
            summary = distilled.summary if distilled else None
            try:
                parsed = client.chat_json(
                    build_absorb_classify_prompt(
                        locale=lang,
                        target_theme=theme,
                        source_theme=source_theme,
                        disambiguation=disambiguation,
                        themes_by_slug=themes_by_slug,
                    ),
                    build_remap_user_prompt(
                        title=raw.raw_title,
                        url=raw.url,
                        summary=summary,
                        existing_tags=detail_tags,
                        body_excerpt=body or "(no body)",
                    ),
                )
                slug = str(parsed.get("theme_slug") or source_slug).strip().lower()
                if slug == target_slug:
                    storage.set_item_theme(raw_id, theme_id, source="remap")
                    absorbed += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning(
                    "Absorb classify failed raw_id=%s source=%s: %s",
                    raw_id,
                    source_slug,
                    exc,
                )
                failed += 1
                skipped += 1

        per_source_stats.append(
            {
                "slug": source_slug,
                "relation": relation,
                "pool_size": pool_size,
                "prefilter_hits": prefiltered_hits,
                "llm_candidates": len(candidate_ids),
                "absorbed": absorbed,
                "skipped": skipped,
                "failed": failed,
            }
        )
        total_absorbed += absorbed
        total_skipped += skipped
        total_failed += failed
        total_candidates += len(candidate_ids)

    storage.record_theme_operation(
        op_type="absorb",
        source_theme_id=theme_id,
        target_theme_ids=[theme_id],
        total_items=total_candidates,
        processed_items=total_absorbed + total_skipped + total_failed,
        metadata={
            "discovery": discovery,
            "per_source_stats": per_source_stats,
            "scan_sources": [item["slug"] for item in scan_plan],
        },
    )

    logger.info(
        "Orchestrated absorb into theme %s (%s): %s absorbed, %s skipped, %s failed / %s candidates; sources=%s",
        theme_id,
        target_slug,
        total_absorbed,
        total_skipped,
        total_failed,
        total_candidates,
        [item["slug"] for item in scan_plan],
    )
    return {
        "theme_id": theme_id,
        "absorbed": total_absorbed,
        "skipped": total_skipped,
        "failed": total_failed,
        "candidates": total_candidates,
        "scan_sources": [item["slug"] for item in scan_plan],
        "related_source_count": max(0, len(scan_plan) - 1),
        "per_source_stats": per_source_stats,
    }


def absorb_from_other_theme(
    storage: SqliteStorage,
    *,
    theme_id: int,
    locale: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper around orchestrated absorb."""
    return orchestrate_theme_absorb(
        storage,
        theme_id=theme_id,
        locale=locale,
        forced_source_slugs=None,
        rediscover=True,
    )


def absorb_from_theme(
    storage: SqliteStorage,
    *,
    target_theme_id: int,
    source_theme_id: int,
    locale: str | None = None,
) -> dict[str, Any]:
    """Move items from a specific source theme into target when LLM agrees."""
    source = storage.get_theme_by_id(source_theme_id)
    if source is None:
        raise ValueError("theme not found")
    source_slug = str(source["slug"]).lower()
    return orchestrate_theme_absorb(
        storage,
        theme_id=target_theme_id,
        locale=locale,
        forced_source_slugs=[source_slug],
        rediscover=True,
    )


def _start_orchestrated_absorb(
    *,
    theme_id: int,
    locale: str | None,
    user_id: int,
    forced_source_slugs: list[str] | None,
    rediscover: bool,
) -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context

    storage = get_storage()
    try:
        with user_context(user_id):
            orchestrate_theme_absorb(
                storage,
                theme_id=theme_id,
                locale=locale,
                forced_source_slugs=forced_source_slugs,
                rediscover=rediscover,
            )
    except Exception:
        logger.exception("Background orchestrated absorb failed theme_id=%s", theme_id)
    finally:
        storage.close()


def _launch_orchestrated_absorb(
    *,
    theme_id: int,
    locale: str | None,
    user_id: int,
    forced_source_slugs: list[str] | None,
    rediscover: bool,
) -> None:
    with _absorb_guard:
        if theme_id in _absorb_running:
            return
        _absorb_running.add(theme_id)
    try:
        _start_orchestrated_absorb(
            theme_id=theme_id,
            locale=locale,
            user_id=user_id,
            forced_source_slugs=forced_source_slugs,
            rediscover=rediscover,
        )
    finally:
        with _absorb_guard:
            _absorb_running.discard(theme_id)


def schedule_orchestrate_absorb(
    *,
    theme_id: int,
    locale: str | None = None,
    user_id: int | None = None,
    forced_source_slugs: list[str] | None = None,
    rediscover: bool = True,
    debounce: bool = False,
) -> dict[str, Any]:
    """Run orchestrated absorb in a background thread (API returns immediately)."""
    from on1y.auth.context import get_current_user_id
    from on1y.config import get_settings
    from on1y.llm.settings import resolve_llm_settings

    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        uid = 1

    if not resolve_llm_settings(user_id=uid).api_key_set:
        return {"started": False, "reason": "no_llm_key", "theme_id": theme_id}

    settings = get_settings()

    def _launch() -> None:
        _launch_orchestrated_absorb(
            theme_id=theme_id,
            locale=locale,
            user_id=uid,
            forced_source_slugs=forced_source_slugs,
            rediscover=rediscover,
        )

    if debounce and settings.absorb_debounce_seconds > 0:
        with _absorb_guard:
            pending = _absorb_pending.pop(theme_id, None)
            if pending is not None:
                pending.cancel()

            def _debounced() -> None:
                with _absorb_guard:
                    _absorb_pending.pop(theme_id, None)
                _launch()

            timer = threading.Timer(settings.absorb_debounce_seconds, _debounced)
            _absorb_pending[theme_id] = timer
            timer.daemon = True
            timer.start()
        return {"started": True, "debounced": True, "theme_id": theme_id}

    with _absorb_guard:
        if theme_id in _absorb_running:
            return {"started": False, "reason": "already_running", "theme_id": theme_id}

    thread = threading.Thread(
        target=_launch,
        name=f"on1y-absorb-theme-{theme_id}",
        daemon=True,
    )
    thread.start()
    return {"started": True, "theme_id": theme_id}


def schedule_absorb_from_other(
    *,
    theme_id: int,
    locale: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    return schedule_orchestrate_absorb(
        theme_id=theme_id,
        locale=locale,
        user_id=user_id,
        rediscover=True,
        debounce=False,
    )


def schedule_absorb_from_theme(
    *,
    target_theme_id: int,
    source_theme_id: int,
    locale: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    from on1y.adapters.sqlite_storage import get_storage

    storage = get_storage()
    try:
        source = storage.get_theme_by_id(source_theme_id)
        if source is None:
            return {"started": False, "reason": "theme_not_found"}
        source_slug = str(source["slug"]).lower()
    finally:
        storage.close()
    return schedule_orchestrate_absorb(
        theme_id=target_theme_id,
        locale=locale,
        user_id=user_id,
        forced_source_slugs=[source_slug],
        rediscover=True,
        debounce=False,
    )
