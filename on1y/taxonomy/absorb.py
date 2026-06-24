"""Pull matching items from「其他」into a newly created theme (theme only, no summary/tags)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.llm.client import get_llm_client
from on1y.taxonomy.constants import OTHER_THEME_SLUG
from on1y.taxonomy.remap import build_remap_user_prompt

logger = logging.getLogger(__name__)

_absorb_guard = threading.Lock()
_absorb_running: set[int | tuple[int, int]] = set()


def build_absorb_system_prompt(*, locale: str, new_theme: dict[str, Any]) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    slug = str(new_theme["slug"])
    if locale.lower().startswith("en"):
        name = str(new_theme.get("name_en") or slug)
        desc = str(new_theme.get("description_en") or new_theme.get("name_en") or "")
    else:
        name = str(new_theme.get("name_zh") or slug)
        desc = str(new_theme.get("description_zh") or new_theme.get("name_zh") or "")
    return f"""You classify whether content belongs in a NEW theme bucket. Respond in {lang} only.

Return ONE JSON object:
{{"theme_slug": "{slug}" or "{OTHER_THEME_SLUG}"}}

Themes (pick exactly one slug):
- "{slug}": {name} — {desc}
- "{OTHER_THEME_SLUG}": Other — content that does NOT primarily belong to the new theme above

Rules:
- Pick "{slug}" only when the content is PRIMARILY about that topic (dominant theme, not a passing mention).
- If uncertain or only loosely related, pick "{OTHER_THEME_SLUG}".
- Use title, summary, and content excerpt; be conservative."""


def absorb_from_other_theme(
    storage: SqliteStorage,
    *,
    theme_id: int,
    locale: str | None = None,
) -> dict[str, Any]:
    """Reassign items from「其他」into `theme_id` when LLM agrees (skips user-pinned themes)."""
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
    if str(theme.get("slug") or "").lower() == OTHER_THEME_SLUG:
        raise ValueError("cannot absorb into built-in other theme")

    other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
    if other_id is None:
        return {"absorbed": 0, "skipped": 0, "failed": 0, "candidates": 0, "reason": "no_other_theme"}

    settings = get_settings()
    lang = locale or settings.llm_locale
    raw_ids = storage.list_raw_ids_by_theme(other_id, exclude_theme_sources=("user",))
    candidates = len(raw_ids)
    if not raw_ids:
        return {"absorbed": 0, "skipped": 0, "failed": 0, "candidates": 0}

    new_slug = str(theme["slug"]).lower()
    client = get_llm_client()
    max_in = settings.llm_distill_max_input_chars
    absorbed = 0
    skipped = 0
    failed = 0

    for raw_id in raw_ids:
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
                build_absorb_system_prompt(locale=lang, new_theme=theme),
                build_remap_user_prompt(
                    title=raw.raw_title,
                    url=raw.url,
                    summary=summary,
                    existing_tags=detail_tags,
                    body_excerpt=body or "(no body)",
                ),
            )
            slug = str(parsed.get("theme_slug") or OTHER_THEME_SLUG).strip().lower()
            if slug == new_slug:
                storage.set_item_theme(raw_id, theme_id, source="remap")
                absorbed += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.warning("Absorb classify failed raw_id=%s: %s", raw_id, exc)
            failed += 1
            skipped += 1

    logger.info(
        "Absorb into theme %s (%s): %s absorbed, %s kept in other, %s failed / %s candidates",
        theme_id,
        new_slug,
        absorbed,
        skipped,
        failed,
        candidates,
    )
    return {
        "theme_id": theme_id,
        "absorbed": absorbed,
        "skipped": skipped,
        "failed": failed,
        "candidates": candidates,
    }


def build_absorb_from_source_prompt(
    *,
    locale: str,
    target_theme: dict[str, Any],
    source_theme: dict[str, Any],
) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    target_slug = str(target_theme["slug"])
    source_slug = str(source_theme["slug"])
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
    return f"""You decide whether content was misclassified. Respond in {lang} only.

Return ONE JSON object:
{{"belongs_in_target": true}} or {{"belongs_in_target": false}}

- Target theme "{target_slug}" ({target_name}): {target_desc}
- Current theme "{source_slug}" ({source_name}): {source_desc}

Rules:
- true only when the content PRIMARILY fits the target theme, not the current one.
- For research vs 科技: product/industry/AI-tool news → 科技; papers/lab science → research.
- If uncertain, return false (keep current classification)."""


def absorb_from_theme(
    storage: SqliteStorage,
    *,
    target_theme_id: int,
    source_theme_id: int,
    locale: str | None = None,
) -> dict[str, Any]:
    """Move items from source_theme into target when LLM agrees (skips user-pinned themes)."""
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

    target = storage.get_theme_by_id(target_theme_id)
    source = storage.get_theme_by_id(source_theme_id)
    if target is None or source is None:
        raise ValueError("theme not found")
    if target.get("archived_at") or source.get("archived_at"):
        raise ValueError("theme archived")

    settings = get_settings()
    lang = locale or settings.llm_locale
    raw_ids = storage.list_raw_ids_by_theme(source_theme_id, exclude_theme_sources=("user",))
    candidates = len(raw_ids)
    if not raw_ids:
        return {"absorbed": 0, "skipped": 0, "failed": 0, "candidates": 0}

    client = get_llm_client()
    max_in = settings.llm_distill_max_input_chars
    absorbed = 0
    skipped = 0
    failed = 0

    for raw_id in raw_ids:
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
                build_absorb_from_source_prompt(
                    locale=lang,
                    target_theme=target,
                    source_theme=source,
                ),
                build_remap_user_prompt(
                    title=raw.raw_title,
                    url=raw.url,
                    summary=summary,
                    existing_tags=detail_tags,
                    body_excerpt=body or "(no body)",
                ),
            )
            if bool(parsed.get("belongs_in_target")):
                storage.set_item_theme(raw_id, target_theme_id, source="remap")
                absorbed += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.warning("Absorb-from-theme failed raw_id=%s: %s", raw_id, exc)
            failed += 1
            skipped += 1

    logger.info(
        "Absorb %s -> %s: %s moved, %s kept, %s failed / %s candidates",
        source_theme_id,
        target_theme_id,
        absorbed,
        skipped,
        failed,
        candidates,
    )
    return {
        "target_theme_id": target_theme_id,
        "source_theme_id": source_theme_id,
        "absorbed": absorbed,
        "skipped": skipped,
        "failed": failed,
        "candidates": candidates,
    }


def schedule_absorb_from_theme(
    *,
    target_theme_id: int,
    source_theme_id: int,
    locale: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    from on1y.auth.context import get_current_user_id, user_context
    from on1y.llm.settings import resolve_llm_settings

    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        uid = 1

    if not resolve_llm_settings(user_id=uid).api_key_set:
        return {"started": False, "reason": "no_llm_key"}

    job_key = (target_theme_id, source_theme_id)
    with _absorb_guard:
        if job_key in _absorb_running:
            return {"started": False, "reason": "already_running", "target_theme_id": target_theme_id}
        _absorb_running.add(job_key)

    def _runner() -> None:
        from on1y.adapters.sqlite_storage import get_storage

        storage = get_storage()
        try:
            with user_context(uid):
                absorb_from_theme(
                    storage,
                    target_theme_id=target_theme_id,
                    source_theme_id=source_theme_id,
                    locale=locale,
                )
        except Exception:
            logger.exception(
                "Background absorb-from-theme failed target=%s source=%s",
                target_theme_id,
                source_theme_id,
            )
        finally:
            storage.close()
            with _absorb_guard:
                _absorb_running.discard(job_key)

    threading.Thread(
        target=_runner,
        name=f"on1y-absorb-{source_theme_id}-to-{target_theme_id}",
        daemon=True,
    ).start()
    return {
        "started": True,
        "target_theme_id": target_theme_id,
        "source_theme_id": source_theme_id,
    }


def schedule_absorb_from_other(
    *,
    theme_id: int,
    locale: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Run absorb in a background thread (create-theme API should return immediately)."""
    from on1y.auth.context import get_current_user_id, user_context
    from on1y.llm.settings import resolve_llm_settings

    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        uid = 1

    if not resolve_llm_settings(user_id=uid).api_key_set:
        return {"started": False, "reason": "no_llm_key"}

    with _absorb_guard:
        if theme_id in _absorb_running:
            return {"started": False, "reason": "already_running", "theme_id": theme_id}
        _absorb_running.add(theme_id)

    def _runner() -> None:
        from on1y.adapters.sqlite_storage import get_storage

        storage = get_storage()
        try:
            with user_context(uid):
                absorb_from_other_theme(storage, theme_id=theme_id, locale=locale)
        except Exception:
            logger.exception("Background absorb failed for theme_id=%s", theme_id)
        finally:
            storage.close()
            with _absorb_guard:
                _absorb_running.discard(theme_id)

    threading.Thread(
        target=_runner,
        name=f"on1y-absorb-theme-{theme_id}",
        daemon=True,
    ).start()
    return {"started": True, "theme_id": theme_id}
