"""Download Economist EPUB editions and extract a readable preview."""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from on1y.config import Settings, get_settings
from on1y.hotlist.github_economist import _github_client

logger = logging.getLogger(__name__)

_SKIP_EPUB_PARTS = re.compile(r"(nav|toc|copyright|cover|titlepage|contents)", re.I)


def economist_epub_cache_path(settings: Settings, edition_date: str) -> Path:
    safe = edition_date.strip().replace("/", "-")
    return settings.data_dir / "economist" / f"{safe}.epub"


def download_epub(url: str, *, settings: Settings | None = None) -> bytes:
    settings = settings or get_settings()
    with _github_client(settings) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def cache_epub(data: bytes, *, settings: Settings, edition_date: str) -> Path:
    path = economist_epub_cache_path(settings, edition_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def load_cached_epub(settings: Settings, edition_date: str) -> bytes | None:
    path = economist_epub_cache_path(settings, edition_date)
    if path.is_file():
        return path.read_bytes()
    return None


def _html_to_text(html: bytes) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "svg"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))


def _chapter_heading(text: str) -> str | None:
    for line in text.split("\n"):
        line = line.strip()
        if len(line) < 4 or len(line) > 160:
            continue
        if line.isdigit():
            continue
        return line
    return None


def parse_epub_preview(
    data: bytes,
    *,
    max_chars: int = 40_000,
    max_chapters: int = 48,
) -> dict[str, Any]:
    """Extract chapter headings and plain-text preview from EPUB bytes."""
    chapters: list[str] = []
    parts: list[str] = []
    total = 0

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted(
            n
            for n in archive.namelist()
            if n.lower().endswith((".xhtml", ".html", ".htm"))
            and not _SKIP_EPUB_PARTS.search(n)
        )
        for name in names:
            if total >= max_chars or len(chapters) >= max_chapters:
                break
            try:
                raw = archive.read(name)
            except KeyError:
                continue
            text = _html_to_text(raw)
            if len(text) < 40:
                continue
            heading = _chapter_heading(text)
            if heading and heading not in chapters:
                chapters.append(heading)
            remaining = max_chars - total
            chunk = text[:remaining]
            if chunk:
                parts.append(chunk)
                total += len(chunk)

    preview = "\n\n".join(parts).strip()
    if len(preview) > max_chars:
        preview = preview[: max_chars - 1].rstrip() + "…"
    return {"chapters": chapters, "text": preview, "char_count": len(preview)}


def format_economist_summary(
    *,
    edition_date: str,
    chapters: list[str],
    preview_text: str,
    parse_error: str | None = None,
    locale: str = "zh",
) -> str:
    """Short digest for the summary panel (like LLM summary on feed items)."""
    zh = not locale.lower().startswith("en")
    lines: list[str] = []
    if edition_date:
        lines.append(
            f"出刊日期 **{edition_date}**。"
            if zh
            else f"Issue date **{edition_date}**."
        )
    n = len(chapters)
    if n:
        lines.append(
            f"本期共 **{n}** 篇文章。"
            if zh
            else f"This issue contains **{n}** articles."
        )
    if parse_error:
        lines.append(
            f"（目录解析未完成：{parse_error}）"
            if zh
            else f"(Table of contents incomplete: {parse_error})"
        )
    if chapters:
        lines.append("")
        lines.append("**目录**" if zh else "**Contents**")
        for title in chapters[:24]:
            lines.append(f"- {title}")
        if len(chapters) > 24:
            lines.append(
                f"- …共 {len(chapters)} 篇"
                if zh
                else f"- …{len(chapters)} articles total"
            )
    elif preview_text.strip():
        snippet = preview_text.strip().replace("\n", " ")[:280]
        lines.append("")
        lines.append(snippet + ("…" if len(preview_text) > 280 else ""))
    return "\n".join(lines).strip()


def format_economist_reader_body(
    *,
    chapters: list[str],
    preview_text: str,
    parse_error: str | None = None,
    locale: str = "zh",
) -> str:
    """Scrollable preview for the original-text panel (no download URL)."""
    zh = not locale.lower().startswith("en")
    lines: list[str] = []
    if parse_error:
        lines.append(
            f"（正文预览暂未解析：{parse_error}）"
            if zh
            else f"(Preview not available: {parse_error})"
        )
        lines.append("")
    if preview_text.strip():
        lines.append(preview_text.strip())
    elif chapters:
        lines.append(
            "请选择「下载 EPUB」获取完整周刊。"
            if zh
            else "Use Download EPUB for the full issue."
        )
    return "\n".join(lines).strip()


def build_economist_preview(
    epub_url: str,
    edition_date: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Download (or load cache), parse EPUB, return body text and metadata."""
    settings = settings or get_settings()
    max_chars = int(getattr(settings, "economist_epub_preview_max_chars", 40_000))

    data: bytes | None = load_cached_epub(settings, edition_date)
    if data is None:
        data = download_epub(epub_url, settings=settings)
        try:
            cache_epub(data, settings=settings, edition_date=edition_date)
        except OSError as exc:
            logger.warning("Could not cache EPUB %s: %s", edition_date, exc)

    parse_error: str | None = None
    chapters: list[str] = []
    preview_text = ""
    try:
        parsed = parse_epub_preview(data, max_chars=max_chars)
        chapters = list(parsed["chapters"])
        preview_text = str(parsed["text"])
        if not preview_text and not chapters:
            parse_error = "未提取到正文"
    except Exception as exc:
        logger.warning("EPUB parse failed for %s: %s", edition_date, exc)
        parse_error = str(exc)

    summary = format_economist_summary(
        edition_date=edition_date,
        chapters=chapters,
        preview_text=preview_text,
        parse_error=parse_error,
    )
    reader_body = format_economist_reader_body(
        chapters=chapters,
        preview_text=preview_text,
        parse_error=parse_error,
    )
    excerpt = preview_text[:400].strip() if preview_text else (
        f"共 {len(chapters)} 篇" if chapters else summary[:200]
    )
    return {
        "summary": summary,
        "body_text": reader_body,
        "excerpt": excerpt,
        "chapters": chapters,
        "chapter_count": len(chapters),
        "preview_chars": len(preview_text),
    }
