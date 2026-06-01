"""Clean subtitle / VTT / SRT dumps for readable original text."""

from __future__ import annotations

import re

from on1y.extract.subtitles import strip_subtitle_markup

HEADING_LINE = re.compile(r"^#{1,6}\s+")
SECTION_MARKERS = ("## 字幕", "## Subtitle", "## Transcript")


def _is_subtitle_dump(text: str) -> bool:
    return (
        "WEBVTT" in text
        or bool(re.search(r"<\d{2}:\d{2}:\d{2}[.,]\d{3}>", text))
        or bool(re.search(r"\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}", text))
        or "## 字幕" in text
        or "## Subtitle" in text
        or "## Transcript" in text
    )


def _extract_title_and_sections(body: str) -> tuple[str, str, str, str]:
    title = ""
    rest = body
    if body.startswith("# "):
        first_nl = body.find("\n")
        title = body[:first_nl].strip() if first_nl > 0 else body.strip()
        rest = body[first_nl + 1 :].lstrip() if first_nl > 0 else ""

    transcript_start = -1
    for marker in SECTION_MARKERS:
        idx = rest.find(marker)
        if idx >= 0 and (transcript_start < 0 or idx < transcript_start):
            transcript_start = idx
    if transcript_start < 0:
        return title, "", rest, ""

    prefix = rest[:transcript_start].strip()
    transcript_block = rest[transcript_start:].strip()
    lines = transcript_block.split("\n", 1)
    header = lines[0]
    raw_transcript = lines[1] if len(lines) > 1 else ""
    return title, prefix, header, raw_transcript


def format_video_body_text(body: str) -> str | None:
    """Return cleaned body when transcript markup is detected, else None."""
    if not _is_subtitle_dump(body):
        return None
    title, prefix, header, raw_transcript = _extract_title_and_sections(body)
    if header and raw_transcript:
        cleaned = strip_subtitle_markup(raw_transcript)
        if not cleaned:
            return None
        section = f"{header}\n\n{cleaned}"
        parts = [p for p in [title, prefix, section] if p]
        return "\n\n".join(parts).strip()
    if _is_subtitle_dump(body):
        cleaned = strip_subtitle_markup(body)
        return cleaned.strip() if cleaned else None
    return None


def format_original_text(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    cleaned = format_video_body_text(text)
    if cleaned:
        return cleaned
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()
