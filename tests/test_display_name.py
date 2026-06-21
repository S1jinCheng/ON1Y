from on1y.books.display_name import (
    enrich_fields_from_candidate,
    format_book_label,
    parse_translator_from_text,
    split_author_country,
)


def test_format_book_label_full_example():
    label = format_book_label(
        title="国富论",
        author="[英]亚当·斯密",
        translator="胡长明",
        publisher="人民日报出版社",
    )
    assert label == "国富论 [英]亚当·斯密 著;胡长明 译 人民日报出版社"


def test_parse_translator_semicolon_pattern():
    text = "国富论 [英]亚当·斯密 著;胡长明 译 人民日报出版社"
    assert parse_translator_from_text(text) == "胡长明"


def test_enrich_from_zlib_title():
    title, author, translator, publisher, language = enrich_fields_from_candidate(
        title="国富论",
        author=None,
        translator=None,
        publisher=None,
        candidate={
            "title": "国富论 [英]亚当·斯密 著;胡长明 译 人民日报出版社",
            "language": "english",
        },
    )
    assert title == "国富论"
    assert translator == "胡长明"
    assert publisher == "人民日报出版社"
    assert "[英]" in (author or "")
    assert language == "english"


def test_split_author_country_bracket():
    country, name = split_author_country("[英]亚当·斯密 著")
    assert country == "英"
    assert name == "亚当·斯密"


def test_format_uses_language_when_no_country():
    label = format_book_label(
        title="国富论",
        author="亚当·斯密",
        translator="胡长明",
        publisher="人民日报出版社",
        language="english",
    )
    assert label == "国富论 [英]亚当·斯密 著;胡长明 译 人民日报出版社"
