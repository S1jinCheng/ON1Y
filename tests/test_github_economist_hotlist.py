"""Tests for GitHub Economist hot-list feed."""

from __future__ import annotations

import io
import zipfile

from on1y.hotlist.epub_preview import (
    format_economist_reader_body,
    format_economist_summary,
    parse_epub_preview,
)
from on1y.hotlist.economist_urls import strip_legacy_economist_body
from on1y.hotlist.github_economist import (
    _EDITION_TITLE_RE,
    _edition_iso,
    _epub_url,
    _parse_edition_title,
    _week_title,
)


def test_edition_title_regex() -> None:
    assert _EDITION_TITLE_RE.match("the economist 2026.05.30")
    m = _EDITION_TITLE_RE.match("the economist 2026.05.30")
    assert m is not None
    assert _edition_iso(m.group(1), m.group(2), m.group(3)) == "2026-05-30"


def test_epub_url() -> None:
    folder = "te_2026.05.30"
    url = _epub_url(folder, raw_base="https://example.com/master")
    assert url.endswith("TheEconomist.2026.05.30.epub")


def test_week_title() -> None:
    assert _week_title(iso_year=2026, iso_week=22) == "经济学人 2026年第22周"


def test_parse_edition_from_commit_message() -> None:
    parts = _parse_edition_title("the economist 2026.05.30\n\nupdate epub")
    assert parts == ("2026", "05", "30")


def test_parse_epub_preview_minimal() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "OEBPS/article01.xhtml",
            (
                '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
                "<body><h1>Leaders</h1><p>Sample article text for preview.</p></body></html>"
            ),
        )
    parsed = parse_epub_preview(buf.getvalue(), max_chars=5000)
    assert "Leaders" in parsed["chapters"] or "Sample article" in parsed["text"]
    summary = format_economist_summary(
        edition_date="2026-05-30",
        chapters=parsed["chapters"],
        preview_text=parsed["text"],
    )
    body = format_economist_reader_body(
        chapters=parsed["chapters"],
        preview_text=parsed["text"],
    )
    assert "目录" in summary or "2026-05-30" in summary
    assert "EPUB" not in body
    legacy = strip_legacy_economist_body(
        "EPUB 下载：https://x.epub\n\n## 正文预览\nHello"
    )
    assert "EPUB" not in legacy
    assert "Hello" in legacy
