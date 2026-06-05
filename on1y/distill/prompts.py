"""Prompt templates for exclusive theme + flat dynamic tags."""

from __future__ import annotations

from typing import Any

PROMPT_VERSION = "v4-exclusive"


def themes_block_for_prompt(themes: list[dict[str, Any]], *, locale: str) -> str:
    lines: list[str] = []
    for theme in themes:
        slug = str(theme["slug"])
        if locale.lower().startswith("en"):
            desc = str(theme.get("description_en") or "")
            lines.append(f'- "{slug}": {theme.get("name_en")} — {desc}')
        else:
            desc = str(theme.get("description_zh") or "")
            lines.append(f'- "{slug}": {theme.get("name_zh")} — {desc}')
    return "\n".join(lines)


def build_system_prompt(*, locale: str, themes: list[dict[str, Any]]) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    theme_block = themes_block_for_prompt(themes, locale=locale)
    return f"""You classify content for a personal knowledge archive. Respond in {lang} only.

Return ONE JSON object (no markdown):
{{
  "summary": "1-2 short sentences: core takeaway",
  "theme": "research",
  "tags": ["tag1", "tag2", "tag3"]
}}

Fixed themes (pick exactly ONE slug — mutually exclusive buckets):
{theme_block}

Rules:
- theme: exactly ONE slug from the list. Choose by dominant topic weight, not minor mentions.
- If uncertain, use "other".
- tags: 3-8 precise flat dynamic labels (like online book tags). No hierarchy.
- Do NOT put theme names or author/creator names into tags.
- summary: MAX 2 sentences.
- Be factual; do not invent.
- ALL text fields must be in {lang}."""


def build_reader_system_prompt(*, locale: str) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    return f"""Rewrite video subtitle/caption text as clean readable prose in {lang}.
Preserve meaning; remove timestamps and duplicate lines; use paragraphs.
Return plain text only (no JSON, no markdown fences). Max ~1200 words."""
