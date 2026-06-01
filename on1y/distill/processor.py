"""Distill one raw_item via LLM into summary, exclusive theme, and flat tags."""

from __future__ import annotations

import logging
import re

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.distill.prompts import (
    PROMPT_VERSION,
    build_reader_system_prompt,
    build_system_prompt,
)
from on1y.llm.client import get_llm_client
from on1y.models.distill import LlmDistillResult
from on1y.taxonomy.constants import OTHER_THEME_SLUG

logger = logging.getLogger(__name__)

_SUBTITLE_HINT_RE = re.compile(
    r"WEBVTT|\d{1,2}:\d{2}(:\d{2})?\s*-->",
    re.IGNORECASE,
)


def list_undistilled_raw_ids(
    storage: SqliteStorage, *, limit: int = 20, platform: str | None = None
) -> list[int]:
    return storage.list_raw_ids_without_distill(limit=limit, platform=platform)


def list_distill_candidate_ids(
    storage: SqliteStorage,
    *,
    limit: int = 20,
    platform: str | None = None,
    force: bool = False,
) -> list[int]:
    if force:
        return storage.list_raw_ids_eligible_for_distill(limit=limit, platform=platform)
    return storage.list_raw_ids_needing_distill(
        prompt_version=PROMPT_VERSION,
        limit=limit,
        platform=platform,
    )


def distill_raw_item(
    storage: SqliteStorage,
    raw_id: int,
    *,
    force: bool = False,
    locale: str | None = None,
) -> int:
    """Run LLM distillation for one raw_item. Returns distilled_items.id."""
    from on1y.config import get_settings

    settings = get_settings()
    raw = storage.get_raw_by_id(raw_id)
    if raw is None:
        raise ValueError(f"raw_item not found: {raw_id}")
    if not raw.body_text or not raw.body_text.strip():
        raise ValueError(f"raw_item {raw_id} has no body text")

    existing = storage.get_distilled_by_raw_id(raw_id)
    if (
        existing
        and not force
        and (existing.prompt_version or "") == PROMPT_VERSION
        and existing.distill_status == "ok"
    ):
        return existing.id

    lang = locale or settings.llm_locale
    max_in = settings.llm_distill_max_input_chars
    body = raw.body_text.strip()
    if len(body) > max_in:
        body = body[:max_in] + "\n[...truncated for fast classify...]"

    active_themes = storage.list_active_themes()
    user_prompt = _build_user_prompt(
        title=raw.raw_title,
        url=raw.url,
        platform=raw.platform,
        body=body,
    )

    client = get_llm_client()
    parsed = client.chat_json(
        build_system_prompt(locale=lang, themes=active_themes),
        user_prompt,
        max_tokens=settings.llm_max_output_tokens,
    )
    result = LlmDistillResult.model_validate(parsed)

    from on1y.llm.settings import resolve_llm_settings

    model = resolve_llm_settings().model
    reader_text = _maybe_generate_reader_text(
        client,
        locale=lang,
        platform=raw.platform,
        body=body,
        settings=settings,
    )
    distilled_id = storage.upsert_distilled(
        raw_id=raw_id,
        summary=_clamp_summary(result.summary),
        key_points=[],
        topics=[],
        model=model,
        prompt_version=PROMPT_VERSION,
        status="ok",
        error=None,
        reader_text=reader_text,
    )

    theme_slug = result.resolved_theme_slug() or OTHER_THEME_SLUG
    if storage.get_raw_theme_source(raw_id) != "user":
        storage.set_item_theme_by_slug(raw_id, theme_slug, source="llm")
    storage.merge_llm_tags(raw_id, result.tags[:8])

    logger.info("Distilled raw_id=%s -> distilled_id=%s", raw_id, distilled_id)
    return distilled_id


def run_distill_batch(
    storage: SqliteStorage,
    limit: int,
    *,
    platform: str | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Run LLM distill on up to `limit` eligible raw items."""
    from on1y.llm.settings import get_resolved_llm_settings

    if not get_resolved_llm_settings().api_key_set:
        logger.warning("Skip distill batch: no LLM API key configured")
        return {"distilled": 0, "failed": 0, "skipped": limit}

    ids = list_distill_candidate_ids(storage, limit=limit, platform=platform, force=force)
    distilled = 0
    failed = 0
    for raw_id in ids:
        try:
            distill_raw_item(storage, raw_id, force=force)
            distilled += 1
        except Exception as exc:
            failed += 1
            logger.warning("Distill failed raw_id=%s: %s", raw_id, exc)
    return {"distilled": distilled, "failed": failed}


def _clamp_summary(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[。！？.!?])\s+", text, maxsplit=2)
    if len(parts) >= 2:
        return "".join(parts[:2]).strip()
    if len(text) > 280:
        return text[:277].rstrip() + "…"
    return text


def _looks_like_subtitle(body: str, platform: str) -> bool:
    if platform.lower() in {"youtube", "bilibili"}:
        return True
    if _SUBTITLE_HINT_RE.search(body[:8000]):
        return True
    return len(re.findall(r"\d{1,2}:\d{2}:\d{2}", body[:12000])) >= 5


def _maybe_generate_reader_text(
    client,
    *,
    locale: str,
    platform: str,
    body: str,
    settings,
) -> str | None:
    if not _looks_like_subtitle(body, platform):
        return None
    excerpt = body[: min(len(body), 12_000)]
    try:
        text = client.chat(
            build_reader_system_prompt(locale=locale),
            f"Subtitle content:\n{excerpt}",
            max_tokens=min(settings.llm_max_output_tokens * 4, 2048),
        )
    except Exception as exc:
        logger.warning("Reader text generation skipped: %s", exc)
        return None
    cleaned = (text or "").strip()
    return cleaned or None


def _build_user_prompt(
    *,
    title: str | None,
    url: str,
    platform: str,
    body: str,
) -> str:
    return f"""Title: {title or "(untitled)"}
Platform: {platform}
URL: {url}

Content:
{body}
"""
