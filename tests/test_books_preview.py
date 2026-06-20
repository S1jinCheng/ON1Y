def test_preview_returns_top_three_popular(monkeypatch):
    from on1y.books.edition_match import EditionHints
    from on1y.books.preview import preview_ebook_candidates
    from on1y.books.zlib_session import ZlibSession

    session = ZlibSession(host="zh.z-lib.help", remix_userid="1", remix_userkey="abc")
    monkeypatch.setattr("on1y.books.preview.load_zlib_session", lambda _uid: session)

    books = [
        {"id": i, "hash": f"h{i}", "title": f"Book {i}", "extension": "pdf", "author": "Author"}
        for i in range(1, 6)
    ]

    class FakeClient:
        def verify(self):
            return True

        def search_popular(self, query, fmt=None, *, limit=3):
            assert limit == 3
            return books[:limit]

    monkeypatch.setattr("on1y.books.preview.ZlibEapiClient", lambda _s: FakeClient())

    result = preview_ebook_candidates(
        1,
        hints=EditionHints(title="国富论", author="亚当·斯密", translator="唐日松"),
    )
    assert result["source"] == "zlib"
    assert len(result["candidates"]) == 3
    assert result["candidates"][0]["title"] == "Book 1"
    assert result["format_filter"] is None
