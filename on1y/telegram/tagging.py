"""Theme + topic tags for Telegram chat sessions (time-chunked transcripts)."""

from __future__ import annotations

import logging

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.models.distill import LlmDistillResult
from on1y.taxonomy.constants import OTHER_THEME_SLUG

logger = logging.getLogger(__name__)

CONVERSATION_CLASSIFY_PROMPT_VERSION = "v1-conversation-classify"

_GROUP_CHAT_TYPES = frozenset({"supergroup", "private_group", "group", "channel"})


def apply_conversation_system_tags(
    storage: SqliteStorage,
    raw_id: int,
    *,
    contact: str,
    chat_type: str,
) -> None:
    """Link contact / chat-kind tags so sessions from the same chat cluster together."""
    contact_text = (contact or "").strip()
    if contact_text:
        tag_id = storage.ensure_flat_tag(contact_text)
        storage.link_item_tag(raw_id, tag_id, confidence=1.0, source="telegram")
    kind_label = "群聊" if chat_type in _GROUP_CHAT_TYPES else "私聊"
    kind_id = storage.ensure_flat_tag(kind_label)
    storage.link_item_tag(raw_id, kind_id, confidence=1.0, source="telegram")


def classify_telegram_session(
    storage: SqliteStorage,
    raw_id: int,
    *,
    locale: str | None = None,
    force: bool = False,
) -> int | None:
    """Assign theme + topic tags to one chat session (summary only, no reader_text)."""
    from on1y.config import get_settings
    from on1y.distill.processor import _build_user_prompt, _clamp_summary
    from on1y.distill.prompts import build_conversation_classify_system_prompt
    from on1y.llm.client import get_llm_client
    from on1y.llm.settings import get_resolved_llm_settings, resolve_llm_settings

    settings = get_settings()
    raw = storage.get_raw_by_id(raw_id)
    if raw is None or not (raw.body_text or "").strip():
        raise ValueError(f"raw_item not found or empty: {raw_id}")

    existing = storage.get_distilled_by_raw_id(raw_id)
    if (
        existing
        and not force
        and existing.distill_status == "ok"
        and (existing.prompt_version or "") == CONVERSATION_CLASSIFY_PROMPT_VERSION
        and (existing.summary or "").strip()
    ):
        return existing.id

    if not get_resolved_llm_settings().api_key_set:
        logger.debug("Skip telegram classify raw_id=%s: no LLM API key", raw_id)
        return None

    lang = locale or settings.llm_locale
    body = raw.body_text.strip()
    max_in = settings.llm_distill_max_input_chars
    if len(body) > max_in:
        body = body[:max_in] + "\n[...truncated for classify...]"

    active_themes = storage.list_active_themes()
    user_prompt = _build_user_prompt(
        title=raw.raw_title,
        url=raw.url,
        platform=raw.platform,
        body=body,
    )
    client = get_llm_client()
    parsed = client.chat_json(
        build_conversation_classify_system_prompt(locale=lang, themes=active_themes),
        user_prompt,
        max_tokens=settings.llm_max_output_tokens,
    )
    result = LlmDistillResult.model_validate(parsed)
    model = resolve_llm_settings().model
    distilled_id = storage.upsert_distilled(
        raw_id=raw_id,
        summary=_clamp_summary(result.summary),
        key_points=[],
        topics=result.tags[:8],
        model=model,
        prompt_version=CONVERSATION_CLASSIFY_PROMPT_VERSION,
        status="ok",
        error=None,
        reader_text=None,
    )
    theme_slug = result.resolved_theme_slug() or OTHER_THEME_SLUG
    if storage.get_raw_theme_source(raw_id) != "user":
        storage.set_item_theme_by_slug(raw_id, theme_slug, source="llm")
    storage.merge_llm_tags(raw_id, result.tags[:8])
    logger.info("Classified telegram raw_id=%s theme=%s tags=%s", raw_id, theme_slug, len(result.tags))
    return distilled_id
