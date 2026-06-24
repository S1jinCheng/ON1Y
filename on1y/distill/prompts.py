"""Prompt templates for exclusive theme + flat dynamic tags."""

from __future__ import annotations

from typing import Any

from on1y.taxonomy.constants import KNOWN_THEME_PAIRS, theme_label

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


def collect_active_disambiguation_pairs(
    themes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pairs from KNOWN_THEME_PAIRS where both themes are active."""
    by_slug = {str(theme["slug"]).lower(): theme for theme in themes}
    name_to_slug: dict[str, str] = {}
    for theme in themes:
        slug = str(theme["slug"]).lower()
        name_to_slug[slug] = slug
        name_zh = str(theme.get("name_zh") or "").strip()
        if name_zh:
            name_to_slug[name_zh] = slug
            name_to_slug[name_zh.casefold()] = slug

    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for theme in themes:
        slug = str(theme["slug"]).lower()
        lookup_keys = {slug, str(theme.get("name_zh") or "").strip().casefold()}
        known: list[Any] = []
        for map_key, map_pairs in KNOWN_THEME_PAIRS.items():
            if map_key.casefold() in lookup_keys or map_key == slug:
                known.extend(map_pairs)
        for pair in known:
            resolved_peer = name_to_slug.get(pair.peer_slug)
            if resolved_peer is None:
                resolved_peer = name_to_slug.get(pair.peer_slug.casefold())
            if resolved_peer is None or resolved_peer not in by_slug:
                continue
            ordered = tuple(sorted((slug, resolved_peer)))
            if ordered in seen:
                continue
            seen.add(ordered)
            pairs.append(
                {
                    "slug_a": slug,
                    "slug_b": resolved_peer,
                    "theme_a": theme,
                    "theme_b": by_slug[resolved_peer],
                    "a_when": pair.new_theme_when,
                    "b_when": pair.peer_when,
                }
            )
    return pairs


def build_disambiguation_block(
    pairs: list[dict[str, Any]],
    *,
    locale: str,
) -> str:
    if not pairs:
        return ""
    lines: list[str] = []
    if locale.lower().startswith("en"):
        lines.append("Theme disambiguation (do not confuse these pairs):")
    else:
        lines.append("主题辨析（以下主题对不可混淆）：")
    for pair in pairs:
        theme_a = pair["theme_a"]
        theme_b = pair["theme_b"]
        slug_a = str(pair["slug_a"])
        slug_b = str(pair["slug_b"])
        name_a = theme_label(theme_a, locale)
        name_b = theme_label(theme_b, locale)
        a_when = str(pair.get("a_when") or "").strip()
        b_when = str(pair.get("b_when") or "").strip()
        if locale.lower().startswith("en"):
            lines.append(f'- "{slug_a}" ({name_a}): {a_when or "see theme description"}')
            lines.append(f'- "{slug_b}" ({name_b}): {b_when or "see theme description"}')
        else:
            lines.append(f'- "{slug_a}"（{name_a}）：{a_when or "见主题描述"}')
            lines.append(f'- "{slug_b}"（{name_b}）：{b_when or "见主题描述"}')
    return "\n" + "\n".join(lines) + "\n"


def build_absorb_disambiguation_block(
    disambiguation: list[dict[str, Any]],
    *,
    theme: dict[str, Any],
    themes_by_slug: dict[str, dict[str, Any]],
    locale: str,
) -> str:
    if not disambiguation:
        return ""
    new_slug = str(theme["slug"]).lower()
    lines: list[str] = []
    if locale.lower().startswith("en"):
        lines.append("Theme disambiguation for this absorb pass:")
    else:
        lines.append("本次迁入的主题辨析：")
    for item in disambiguation:
        peer_slug = str(item.get("peer_slug") or "").lower()
        peer = themes_by_slug.get(peer_slug)
        if peer is None:
            continue
        new_name = theme_label(theme, locale)
        peer_name = theme_label(peer, locale)
        new_when = str(item.get("new_theme_when") or "").strip()
        peer_when = str(item.get("peer_when") or "").strip()
        if locale.lower().startswith("en"):
            lines.append(f'- "{new_slug}" ({new_name}): {new_when}')
            lines.append(f'- "{peer_slug}" ({peer_name}): {peer_when}')
        else:
            lines.append(f'- "{new_slug}"（{new_name}）：{new_when}')
            lines.append(f'- "{peer_slug}"（{peer_name}）：{peer_when}')
    if len(lines) <= 1:
        return ""
    return "\n" + "\n".join(lines) + "\n"


def theme_disambiguation_block(themes: list[dict[str, Any]], *, locale: str) -> str:
    pairs = collect_active_disambiguation_pairs(themes)
    return build_disambiguation_block(pairs, locale=locale)


def build_system_prompt(*, locale: str, themes: list[dict[str, Any]]) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    theme_block = themes_block_for_prompt(themes, locale=locale)
    disambiguation = theme_disambiguation_block(themes, locale=locale)
    return f"""You classify content for a personal knowledge archive. Respond in {lang} only.

Return ONE JSON object (no markdown):
{{
  "summary": "1-2 short sentences: core takeaway",
  "theme": "research",
  "tags": ["tag1", "tag2", "tag3"]
}}

Fixed themes (pick exactly ONE slug — mutually exclusive buckets):
{theme_block}
{disambiguation}
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
