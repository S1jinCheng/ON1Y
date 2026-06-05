"""LLM flat tags for hot-list questions (research browsing, no theme assignment)."""

from __future__ import annotations

import logging
from typing import Any

from on1y.ports.storage import StoragePort

logger = logging.getLogger(__name__)

HOTLIST_TAG_PROMPT_VERSION = "hotlist-tags-v1"


def build_hotlist_tag_system_prompt(*, locale: str) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    return f"""You label hot-list items (news questions or daily articles) for research browsing. Respond in {lang} only.

Return ONE JSON object (no markdown):
{{"tags": ["tag1", "tag2", "tag3", "tag4"]}}

Rules:
- 3-6 short flat dynamic tags (domain, method, audience, stance if inferable).
- Use title and excerpt only; do not invent facts beyond the text (works for Zhihu questions or Economist articles).
- No theme bucket names; no author/creator names; no hashtags; no duplicate tags.
- ALL tag strings must be in {lang}."""


def _build_hotlist_tag_user_prompt(
    *,
    title: str,
    excerpt: str,
    heat_text: str,
) -> str:
    parts = [f"Title: {title.strip()}"]
    if excerpt.strip():
        parts.append(f"Excerpt: {excerpt.strip()}")
    if heat_text.strip():
        parts.append(f"Heat: {heat_text.strip()}")
    return "\n\n".join(parts)


def needs_hotlist_tags(meta: dict[str, Any], *, snapshot_date: str, force: bool = False) -> bool:
    if force:
        return True
    if meta.get("hotlist_tags_version") != HOTLIST_TAG_PROMPT_VERSION:
        return True
    if str(meta.get("snapshot_date") or "") != snapshot_date:
        return True
    return False


def distill_hotlist_tags(
    storage: StoragePort,
    raw_id: int,
    *,
    title: str,
    excerpt: str,
    heat_text: str = "",
    locale: str | None = None,
    snapshot_date: str,
    force: bool = False,
) -> list[str]:
    """Assign research-oriented flat tags via LLM. Returns tag names applied."""
    from on1y.config import get_settings
    from on1y.exceptions import ConfigurationError
    from on1y.llm.client import get_llm_client

    settings = get_settings()
    raw = storage.get_raw_by_id(raw_id)
    if raw is None:
        raise ValueError(f"raw_item not found: {raw_id}")

    meta = dict(raw.source_meta or {})
    if not needs_hotlist_tags(meta, snapshot_date=snapshot_date, force=force):
        return storage.get_item_tag_names(raw_id)

    lang = locale or settings.llm_locale
    client = get_llm_client()
    try:
        parsed = client.chat_json(
            build_hotlist_tag_system_prompt(locale=lang),
            _build_hotlist_tag_user_prompt(
                title=title,
                excerpt=excerpt,
                heat_text=heat_text,
            ),
            max_tokens=256,
        )
    except ConfigurationError:
        raise
    except Exception as exc:
        logger.warning("Hotlist tag LLM failed raw_id=%s: %s", raw_id, exc)
        raise

    raw_tags = parsed.get("tags") if isinstance(parsed, dict) else None
    if not isinstance(raw_tags, list):
        raw_tags = []
    names: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        label = str(item).strip().lstrip("#")
        if not label or label in seen:
            continue
        seen.add(label)
        names.append(label[:40])
        if len(names) >= 6:
            break

    if names:
        storage.merge_llm_tags(raw_id, names)

    storage.merge_source_meta(
        raw_id,
        {
            "hotlist_tags_version": HOTLIST_TAG_PROMPT_VERSION,
            "snapshot_date": snapshot_date,
        },
    )
    return names
