"""Subtitle language selection, parsing, and locale-aware assembly."""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# yt-dlp language codes — order = priority within each group
ZH_LANG_PRIORITY = ("zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh", "ai-zh", "cmn", "chi")
EN_LANG_PRIORITY = ("en-orig", "en-US", "en-GB", "en", "ai-en")

DEFAULT_SUBTITLE_LANGS = ",".join([*ZH_LANG_PRIORITY, *EN_LANG_PRIORITY])

_LANG_FROM_NAME = re.compile(
    r"\.(?P<lang>(?:zh(?:-Hans|-Hant|-CN|-TW)?|en(?:-orig|-US|-GB)?))(?:\.(?:vtt|srt|ass))?$",
    re.IGNORECASE,
)
VTT_INLINE_TAG = re.compile(r"</?(?:c|\d{2}:\d{2}:\d{2}[.,]\d{3})>")
# VTT (1:23.456) and SRT (00:01:23,456) cue timestamps — often inline on one line (Bilibili)
CUE_TIMESTAMP = re.compile(
    r"(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*"
)
VTT_CUE_LINE = re.compile(
    r"^(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*$"
)
META_LINE = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE|STYLE)", re.I)


def parse_subtitle_langs(lang_config: str | list[str]) -> list[str]:
    """Parse ON1Y_YTDLP_SUB_LANGS comma-separated list."""
    if isinstance(lang_config, list):
        langs = [part.strip() for part in lang_config if part.strip()]
    else:
        langs = [part.strip() for part in lang_config.split(",") if part.strip()]
    return langs or list(ZH_LANG_PRIORITY) + list(EN_LANG_PRIORITY)


def yt_dlp_subtitle_request_langs(lang_config: str | None = None) -> list[str]:
    """Languages passed to yt-dlp subtitleslangs (keep small to avoid 429)."""
    _ = parse_subtitle_langs(lang_config or DEFAULT_SUBTITLE_LANGS)
    return ["zh-CN", "zh-Hans", "zh-Hant", "zh-TW", "zh", "en"]


def detect_lang_group(lang_code: str) -> str | None:
    """Return 'zh', 'en', or None."""
    code = lang_code.lower()
    if code.startswith("zh") or code in {"cmn", "chi", "ai-zh"}:
        return "zh"
    if code.startswith("en") or code == "ai-en":
        return "en"
    return None


def lang_code_from_path(path: Path) -> str | None:
    """Extract language code from yt-dlp subtitle filename (e.g. video.zh-Hans.vtt)."""
    name = path.stem
    if "." in name:
        candidate = name.rsplit(".", 1)[-1]
        if detect_lang_group(candidate):
            return candidate
    match = _LANG_FROM_NAME.search(path.name)
    if match:
        return match.group("lang")
    return None


def _priority_index(lang: str, priority: tuple[str, ...]) -> int:
    lang_lower = lang.lower()
    for idx, code in enumerate(priority):
        if lang_lower == code.lower() or lang_lower.startswith(code.lower() + "-"):
            return idx
    return len(priority) + 10


def pick_best_per_group(
    files: list[Path],
) -> dict[str, Path]:
    """Pick one subtitle file each for zh and en (highest priority lang code)."""
    grouped: dict[str, list[tuple[int, Path, str]]] = {"zh": [], "en": []}
    for path in files:
        lang = lang_code_from_path(path)
        if not lang:
            continue
        group = detect_lang_group(lang)
        if group not in grouped:
            continue
        priority = ZH_LANG_PRIORITY if group == "zh" else EN_LANG_PRIORITY
        grouped[group].append((_priority_index(lang, priority), path, lang))

    chosen: dict[str, Path] = {}
    for group, items in grouped.items():
        if not items:
            continue
        items.sort(key=lambda x: x[0])
        chosen[group] = items[0][1]
        logger.debug("Selected %s subtitle: %s (%s)", group, items[0][1].name, items[0][2])
    return chosen


def _dedupe_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return out


def _group_lines_into_paragraphs(lines: list[str]) -> str:
    paragraphs: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        value = buffer.strip()
        if value:
            paragraphs.append(value)
        buffer = ""

    for line in lines:
        buffer += f" {line}" if buffer else line
        if re.search(r"[。！？.!?…]$", line) or len(buffer) >= 160:
            flush()
    flush()
    return "\n\n".join(paragraphs)


def strip_subtitle_markup(content: str) -> str:
    """Turn raw VTT/SRT text into readable transcript prose."""
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = VTT_INLINE_TAG.sub("", raw_line)
        line = CUE_TIMESTAMP.sub("", line)
        line = html.unescape(line.strip())
        if not line or META_LINE.match(line) or VTT_CUE_LINE.match(line) or line.isdigit():
            continue
        lines.append(line)
    lines = _dedupe_lines(lines)
    if not lines:
        return ""
    return _group_lines_into_paragraphs(lines)


def read_subtitle_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return strip_subtitle_markup(raw).strip()


def _normalize_prefer_lang(prefer_lang: str | None) -> str:
    value = (prefer_lang or "zh").strip().lower()
    if value.startswith("en"):
        return "en"
    return "zh"


def collect_bilingual_subtitles(
    directory: Path,
    *,
    lang_config: str,
    prefer_lang: str | None = None,
) -> tuple[str, list[str]]:
    """
    Read subtitle files from yt-dlp output directory.
    Returns (combined transcript text, list of lang groups found: zh/en).
    When prefer_lang is zh (default), emit Chinese only if available, else English.
    """
    prefer = _normalize_prefer_lang(prefer_lang)
    allowed = {code.lower() for code in parse_subtitle_langs(lang_config)}
    candidates: list[Path] = []
    for path in directory.iterdir():
        if path.suffix.lower() not in {".vtt", ".srt", ".ass"}:
            continue
        lang = lang_code_from_path(path)
        if lang and lang.lower() not in allowed:
            group = detect_lang_group(lang)
            if not group:
                continue
        candidates.append(path)

    if not candidates:
        return "", []

    selected = pick_best_per_group(candidates)
    order: list[str]
    if prefer == "zh":
        order = ["zh", "en"]
    else:
        order = ["en", "zh"]

    sections: list[str] = []
    found: list[str] = []
    for group in order:
        path = selected.get(group)
        if path is None:
            continue
        text = read_subtitle_file(path)
        if not text:
            continue
        if group == "zh":
            sections.append("## 字幕（中文）\n")
        else:
            sections.append("## Subtitle (English)\n")
        sections.append(text)
        found.append(group)
        break

    # Fallback: any single file if grouping failed
    if not sections and candidates:
        best = sorted(candidates)[0]
        text = read_subtitle_file(best)
        if text:
            lang = lang_code_from_path(best)
            group = detect_lang_group(lang or "") if lang else None
            if group == "zh":
                sections.append("## 字幕（中文）\n")
            elif group == "en":
                sections.append("## Subtitle (English)\n")
            else:
                sections.append("## Transcript\n")
            sections.append(text)
            if group:
                found.append(group)

    return "\n\n".join(sections).strip(), found


def is_substantive_subtitle(text: str, *, min_chars: int = 15) -> bool:
    """True when stripped transcript has enough readable content."""
    if not text.strip():
        return False
    prose = strip_subtitle_markup(text)
    for marker in ("## 字幕", "## Subtitle", "## Transcript", "## Description"):
        prose = prose.replace(marker, "")
    prose = re.sub(r"^#+\s*", "", prose, flags=re.MULTILINE)
    prose = re.sub(r"\s+", "", prose)
    return len(prose) >= min_chars


def build_video_body(
    *,
    title: str | None,
    subtitle_text: str,
    description: str | None,
    langs_found: list[str],
    prefer_lang: str | None = "zh",
) -> tuple[str, str | None]:
    """
    Assemble final body and optional partial reason.
    Returns (body_text, partial_reason).
    """
    if subtitle_text and not is_substantive_subtitle(subtitle_text):
        subtitle_text = ""

    parts: list[str] = []
    if title:
        parts.append(f"# {title}\n")

    if subtitle_text:
        parts.append(subtitle_text)
        partial = None
        if len(langs_found) == 1:
            only = langs_found[0]
            pref = _normalize_prefer_lang(prefer_lang)
            if not ((pref == "zh" and only == "zh") or (pref == "en" and only == "en")):
                partial = f"single_subtitle_lang:{only}"
        return "\n".join(parts).strip(), partial

    if description:
        parts.append("## Description\n")
        parts.append(description[:50_000])
        return "\n".join(parts).strip(), "no_subtitles_used_description"

    return "", "no_subtitles_available"
