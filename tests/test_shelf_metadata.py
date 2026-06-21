from on1y.books.edition_match import EditionHints
from on1y.books.shelf_metadata import (
    edition_aligns_with_douban,
    resolve_shelf_metadata,
)


def test_mismatch_parses_candidate_translator():
    hints = EditionHints(title="国富论", author="亚当·斯密", translator="唐日松")
    candidate = {
        "title": "国富论 [英]亚当·斯密 著;胡长明 译 人民日报出版社",
        "author": "亚当·斯密",
        "publisher": "人民日报出版社",
        "language": "english",
    }
    assert not edition_aligns_with_douban(hints, candidate)
    meta = resolve_shelf_metadata(hints, candidate)
    assert meta["translator"] == "胡长明"
    assert meta["publisher"] == "人民日报出版社"
    assert meta["douban_enrich"] is False


def test_mismatch_uses_candidate_not_douban_translator():
    hints = EditionHints(title="国富论", author="亚当·斯密", translator="唐日松")
    candidate = {
        "title": "国富论（上下册）",
        "author": "亚当·斯密",
        "publisher": "商务印书馆",
    }
    assert not edition_aligns_with_douban(hints, candidate)
    meta = resolve_shelf_metadata(hints, candidate)
    assert meta["translator"] is None
    assert meta["douban_enrich"] is False
    assert meta["summary"] and "唐日松" in meta["summary"]
    assert "douban_enrich: false" in meta["notes_extra"]


def test_aligned_keeps_douban_translator():
    hints = EditionHints(title="国富论", author="亚当·斯密", translator="唐日松")
    candidate = {
        "title": "国富论 唐日松 译",
        "author": "亚当·斯密",
    }
    assert edition_aligns_with_douban(hints, candidate)
    meta = resolve_shelf_metadata(hints, candidate)
    assert meta["translator"] == "唐日松"
    assert meta["douban_enrich"] is True
    assert meta["summary"] is None


def test_aligned_tang_risong_in_author_blob():
    hints = EditionHints(title="国富论", author="[英] 亚当·斯密", translator="唐日松")
    candidate = {
        "title": "国富论",
        "author": "〔英〕亚当·斯密著; 唐日松等译",
        "publisher": "华夏出版社",
    }
    assert edition_aligns_with_douban(hints, candidate)
    meta = resolve_shelf_metadata(hints, candidate)
    assert meta["douban_enrich"] is True
