"""One-shot LLM theme split / bulk remap (no preview step)."""

from __future__ import annotations

import logging
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.llm.client import get_llm_client
from on1y.taxonomy.constants import OTHER_THEME_SLUG

logger = logging.getLogger(__name__)


def build_remap_system_prompt(*, locale: str, target_themes: list[dict[str, Any]]) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    lines: list[str] = []
    for theme in target_themes:
        slug = str(theme["slug"])
        if locale.lower().startswith("en"):
            desc = str(theme.get("description_en") or theme.get("name_en") or "")
            lines.append(f'- "{slug}": {theme.get("name_en")} — {desc}')
        else:
            desc = str(theme.get("description_zh") or theme.get("name_zh") or "")
            lines.append(f'- "{slug}": {theme.get("name_zh")} — {desc}')
    theme_block = "\n".join(lines)
    return f"""You reassign content to exactly ONE theme bucket. Respond in {lang} only.

Return ONE JSON object:
{{"theme_slug": "slug", "tags": ["tag1", "tag2"]}}

Target themes (pick exactly one slug):
{theme_block}

Rules:
- Choose the single best-fit theme by overall topic weight, not minor mentions.
- If a piece mentions AI briefly but is mainly about robotics, choose robotics.
- Prefer explicit topic signals in title, summary, and dominant paragraphs.
- tags: 3-6 precise flat labels for the content (helps future retrieval).
- tags must NOT duplicate theme names.
- If nothing fits well, use "{OTHER_THEME_SLUG}".
- ALL tag text must be in {lang}."""


def build_remap_user_prompt(
    *,
    title: str | None,
    url: str,
    summary: str | None,
    existing_tags: list[str],
    body_excerpt: str,
) -> str:
    tag_line = ", ".join(existing_tags) if existing_tags else "(none)"
    return f"""Title: {title or "(untitled)"}
URL: {url}
Summary: {summary or "(none)"}
Existing tags: {tag_line}

Content excerpt:
{body_excerpt}
"""


def split_theme_one_shot(
    storage: SqliteStorage,
    *,
    source_theme_id: int,
    new_themes: list[dict[str, str]],
    locale: str | None = None,
    archive_source: bool = True,
) -> dict[str, Any]:
    """Split source theme into new themes and remap all items in one pass."""
    from on1y.config import get_settings

    settings = get_settings()
    lang = locale or settings.llm_locale

    source = storage.get_theme_by_id(source_theme_id)
    if source is None:
        raise ValueError(f"theme not found: {source_theme_id}")
    if source.get("archived_at"):
        raise ValueError(f"theme already archived: {source['slug']}")

    created: list[dict[str, Any]] = []
    target_ids: list[int] = []
    for spec in new_themes:
        row = storage.create_theme(
            slug=spec.get("slug") or "",
            name_zh=spec["name_zh"],
            name_en=spec.get("name_en") or spec["name_zh"],
            description_zh=spec.get("description_zh") or "",
            description_en=spec.get("description_en") or "",
            sort_order=int(spec.get("sort_order") or 0) or None,
        )
        created.append(row)
        target_ids.append(int(row["id"]))

    target_rows = [storage.get_theme_by_id(tid) for tid in target_ids]
    target_rows = [r for r in target_rows if r is not None]

    raw_ids = storage.list_raw_ids_by_theme(source_theme_id)
    client = get_llm_client()
    max_in = settings.llm_distill_max_input_chars
    remapped = 0
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
                build_remap_system_prompt(locale=lang, target_themes=target_rows),
                build_remap_user_prompt(
                    title=raw.raw_title,
                    url=raw.url,
                    summary=summary,
                    existing_tags=detail_tags,
                    body_excerpt=body,
                ),
            )
            slug = str(parsed.get("theme_slug") or OTHER_THEME_SLUG).strip().lower()
            theme_id = storage.get_theme_id_by_slug(slug)
            if theme_id is None or theme_id not in target_ids:
                other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
                theme_id = other_id if other_id in target_ids else target_ids[0]
            tag_names = parsed.get("tags") if isinstance(parsed.get("tags"), list) else []
            tag_names = [str(t).strip() for t in tag_names if str(t).strip()][:8]

            storage.set_item_theme(raw_id, theme_id, source="remap")
            if tag_names:
                storage.merge_llm_tags(raw_id, tag_names)
            remapped += 1
        except Exception as exc:
            logger.warning("Remap failed raw_id=%s: %s", raw_id, exc)
            failed += 1
            other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
            fallback = other_id if other_id and other_id in target_ids else target_ids[0]
            storage.set_item_theme(raw_id, fallback, source="remap")

    if archive_source:
        storage.archive_theme(source_theme_id, reassign_to_other=False)

    op_id = storage.record_theme_operation(
        op_type="split",
        source_theme_id=source_theme_id,
        target_theme_ids=target_ids,
        total_items=len(raw_ids),
        processed_items=remapped,
    )

    return {
        "operation_id": op_id,
        "source_theme_id": source_theme_id,
        "new_themes": created,
        "remapped": remapped,
        "failed": failed,
        "archived_source": archive_source,
    }
