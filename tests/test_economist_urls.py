"""Tests for Economist download URL resolution."""

from __future__ import annotations

from on1y.hotlist.economist_urls import resolve_economist_epub_url


def test_pdf_url_becomes_epub() -> None:
    pdf = (
        "https://raw.githubusercontent.com/hehonghui/awesome-english-ebooks/master/"
        "01_economist/te_2026.05.30/TheEconomist.2026.05.30.pdf"
    )
    epub = resolve_economist_epub_url(pdf, {})
    assert epub.endswith(".epub")
    assert ".pdf" not in epub
