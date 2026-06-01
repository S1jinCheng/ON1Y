"""Classify stored video transcript bodies."""

from __future__ import annotations

import re

_ZH_SECTION = re.compile(r"^##\s*字幕", re.MULTILINE)
_EN_SECTION = re.compile(r"^##\s*Subtitle(?:\s*\(English\))?", re.MULTILINE)
_TRANSCRIPT_SECTION = re.compile(r"^##\s*Transcript\b", re.MULTILINE)
_DESCRIPTION_SECTION = re.compile(r"^##\s*Description\b", re.MULTILINE)

_SECTION_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("zh", _ZH_SECTION),
    ("en", _EN_SECTION),
    ("en", _TRANSCRIPT_SECTION),
    ("description", _DESCRIPTION_SECTION),
)


def normalize_transcript_sections(body: str) -> str:
    """Ensure embedded section headers start on their own lines."""
    text = (body or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s*(## Subtitle \(English\))", r"\n\n\1\n\n", text)
    text = re.sub(r"\s*(## 字幕[^\n]*)", r"\n\n\1\n\n", text)
    text = re.sub(r"\s+(## Subtitle)(?!\s*\(English\))", r"\n\n\1\n\n", text)
    text = re.sub(r"\s+(## Transcript\b)", r"\n\n\1\n\n", text)
    text = re.sub(r"\s+(## Description\b)", r"\n\n\1\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _classify_heading(heading: str) -> str:
    value = heading.strip()
    if value.startswith("字幕"):
        return "zh"
    if re.match(r"Subtitle(?:\s*\(English\))?", value, re.I):
        return "en"
    if value.lower().startswith("transcript"):
        return "en"
    if value.lower().startswith("description"):
        return "description"
    return "other"


def _parse_sections(body: str) -> tuple[str, list[tuple[str, str, str]]]:
    text = normalize_transcript_sections(body)
    if not text:
        return "", []

    title = ""
    sections: list[tuple[str, str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        content = "\n".join(current_lines).strip()
        if current_heading or content:
            sections.append(
                (
                    _classify_heading(current_heading) if current_heading else "other",
                    current_heading,
                    content,
                )
            )
        current_heading = ""
        current_lines = []

    for line in text.splitlines():
        if re.match(r"^#\s+", line) and not re.match(r"^##\s+", line):
            flush()
            title = line[2:].strip()
            continue
        if re.match(r"^##\s+", line):
            flush()
            current_heading = line[3:].strip()
            continue
        current_lines.append(line)
    flush()
    return title, sections


def _normalize_prefer_lang(prefer_lang: str | None) -> str:
    value = (prefer_lang or "zh").strip().lower()
    if value.startswith("en"):
        return "en"
    return "zh"


def pick_single_transcript(body: str, prefer_lang: str | None = "zh") -> str:
    """Keep one transcript section for the preferred locale."""
    prefer = _normalize_prefer_lang(prefer_lang)
    title, sections = _parse_sections(body)
    if not sections:
        return normalize_transcript_sections(body)

    order = ("zh", "en", "description", "other") if prefer == "zh" else ("en", "zh", "description", "other")
    for kind in order:
        for section_kind, heading, content in sections:
            if section_kind != kind or not content.strip():
                continue
            parts: list[str] = []
            if title:
                parts.append(f"# {title}")
            if heading:
                parts.append(f"## {heading}")
            parts.append(content.strip())
            return "\n\n".join(parts).strip()

    return normalize_transcript_sections(body)


def classify_transcript(body: str | None, prefer_lang: str | None = "zh") -> str:
    """
    Returns one of: zh | en | none | other
    - none: no downloadable subtitles (description-only or empty)
    """
    text = pick_single_transcript(body or "", prefer_lang=prefer_lang)
    if not text.strip():
        return "none"
    if _ZH_SECTION.search(text):
        return "zh"
    if _EN_SECTION.search(text) or _TRANSCRIPT_SECTION.search(text):
        return "en"
    if _DESCRIPTION_SECTION.search(text):
        return "none"
    return "other"


def extract_transcript_plain(body: str, prefer_lang: str | None = "zh") -> str:
    """Pull transcript prose from a structured body (drop title/headers)."""
    text = pick_single_transcript(body, prefer_lang=prefer_lang)
    if not text:
        return ""
    markers = (
        "## 字幕（中文）",
        "## 字幕",
        "## Subtitle (English)",
        "## Subtitle",
        "## Transcript",
        "## Description",
    )
    start = -1
    marker = ""
    for item in markers:
        idx = text.find(item)
        if idx < 0:
            continue
        if start < 0 or idx < start or (idx == start and len(item) > len(marker)):
            start = idx
            marker = item
    if start < 0:
        if text.startswith("# "):
            first_nl = text.find("\n")
            return text[first_nl + 1 :].strip() if first_nl > 0 else text
        return text
    chunk = text[start + len(marker) :].strip()
    if chunk.startswith("（中文）"):
        chunk = chunk.split("\n", 1)[-1].strip()
    return chunk


def body_has_dual_transcripts(body: str | None) -> bool:
    text = normalize_transcript_sections(body or "")
    return bool(_ZH_SECTION.search(text) and (_EN_SECTION.search(text) or _TRANSCRIPT_SECTION.search(text)))
