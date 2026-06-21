from on1y.books.providers.parsers.douban_book import _split_abstract
from on1y.books.translator_match import translator_matches_hint


def test_split_abstract_three_parts_with_translator():
    author, translator, publisher, pub_meta = _split_abstract(
        "[英] 亚当·斯密 / 唐日松 / 华夏出版社"
    )
    assert translator == "唐日松"
    assert publisher == "华夏出版社"
    assert pub_meta is None


def test_split_abstract_four_parts_without_translator():
    author, translator, publisher, pub_meta = _split_abstract(
        "[英] 亚当·斯密 / 华夏出版社 / 2005-1 / 平装"
    )
    assert translator is None
    assert publisher == "华夏出版社"
    assert "2005" in (pub_meta or "")


def test_translator_matches_tang_risong_variant():
    candidate = {
        "title": "国富论",
        "author": "〔英〕亚当·斯密著; 唐日松等译",
        "publisher": "华夏出版社",
    }
    assert translator_matches_hint("唐日松", candidate)
    assert translator_matches_hint("唐日松等", candidate)
    assert not translator_matches_hint("胡长明", candidate)


def test_translator_mismatch_when_publisher_was_wrong_hint():
    """Mis-parsed publisher-as-translator should not trigger false mismatch."""
    candidate = {
        "title": "国富论",
        "author": "〔英〕亚当·斯密著; 唐日松等译",
        "publisher": "华夏出版社",
    }
    assert translator_matches_hint("华夏出版社", candidate)
