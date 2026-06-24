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


def theme_disambiguation_block(themes: list[dict[str, Any]], *, locale: str) -> str:
    slugs = {str(theme.get("slug") or "").strip().lower() for theme in themes}
    name_zh = {str(theme.get("name_zh") or "").strip() for theme in themes}
    has_research = "research" in slugs
    has_tech = "technology" in slugs or "科技" in slugs or "科技" in name_zh
    if not (has_research and has_tech):
        return ""
    if locale.lower().startswith("en"):
        return """
Theme disambiguation — research vs technology (科技):
- research: academic papers, lab experiments, scientific methods, grant/project reports.
- technology / 科技: product launches, gadgets, apps, industry news, AI tools/products, engineering practice.
- Consumer tech, software tutorials, startup/industry updates → technology / 科技, NOT research.
- Peer-reviewed science, replication studies, bench experiments → research, NOT technology.
"""
    return """
主题辨析 — 科研 vs 科技：
- research（科研）：学术论文、科研项目、实验与方法论、理工科基础研究。
- technology / 科技：数码产品、软件应用、互联网、AI 产品/行业动态、工程实践与产业资讯。
- 消费电子评测、编程实战、大模型产品发布、公司/行业新闻 → 科技，不是科研。
- 论文解读、实验复现、课题/基金、实验室研究 → 科研，不是科技。
"""


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
