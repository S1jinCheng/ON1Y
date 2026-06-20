def test_score_prefers_translator():
    from on1y.books.edition_match import EditionHints, pick_best_index

    hints = EditionHints(title="国富论", author="亚当·斯密", translator="唐日松")
    candidates = [
        "国富论 郭大力 王亚南 译",
        "国富论 唐日松 译 商务印书馆",
        "The Wealth of Nations",
    ]
    assert pick_best_index(candidates, hints) == 1


def test_match_quality_low_without_translator():
    from on1y.books.edition_match import EditionHints, match_quality

    hints = EditionHints(title="国富论", translator="唐日松")
    assert match_quality(hints, "国富论 郭大力 王亚南") == "low"


def test_search_query_includes_author_and_translator():
    from on1y.books.edition_match import EditionHints

    hints = EditionHints(title="国富论", author="亚当·斯密", translator="唐日松")
    q = hints.search_query()
    assert "国富论" in q
    assert "亚当·斯密" in q
    assert "唐日松" in q


def test_score_reasons_lists_translator_miss():
    from on1y.books.edition_match import EditionHints, score_reasons

    hints = EditionHints(title="国富论", author="亚当·斯密", translator="唐日松")
    score, reasons = score_reasons("国富论 郭大力 王亚南", hints)
    assert score < 50
    assert any("未找到译者" in r["label"] for r in reasons)


def test_validate_epub_zip():
    import io
    import zipfile

    from on1y.books.file_validate import validate_ebook_bytes

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("content.opf", "x" * 2048)
    result = validate_ebook_bytes(buf.getvalue(), "epub")
    assert result["ok"] is True
