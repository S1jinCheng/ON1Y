def test_format_first_prefers_preferred_format():
    from on1y.books.acquire_strategy import pick_zlib_candidate

    hints = __import__("on1y.books.edition_match", fromlist=["EditionHints"]).EditionHints(
        title="国富论",
        translator="唐日松",
    )
    books_by_fmt = {
        "pdf": [{"title": "国富论", "author": "唐日松 译", "id": 1, "hash": "a"}],
        "epub": [{"title": "国富论", "author": "郭大力 译", "id": 2, "hash": "b"}],
    }
    pick = pick_zlib_candidate(
        books_by_fmt,
        hints,
        strategy="format_first",
        preferred_format="epub",
        format_order=["epub", "pdf"],
    )
    assert pick is not None
    assert pick.fmt == "epub"


def test_match_first_picks_better_translator():
    from on1y.books.acquire_strategy import pick_zlib_candidate
    from on1y.books.edition_match import EditionHints

    hints = EditionHints(title="国富论", translator="唐日松")
    books_by_fmt = {
        "pdf": [{"title": "国富论", "author": "郭大力 译", "id": 1, "hash": "a"}],
        "epub": [{"title": "国富论", "author": "唐日松 译", "id": 2, "hash": "b"}],
    }
    pick = pick_zlib_candidate(
        books_by_fmt,
        hints,
        strategy="match_first",
        preferred_format="pdf",
        format_order=["epub", "pdf"],
    )
    assert pick is not None
    assert pick.fmt == "epub"
