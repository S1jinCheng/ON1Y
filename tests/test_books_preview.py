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

        def book_detail(self, book_id, book_hash):
            return {
                "book": {
                    "id": book_id,
                    "hash": book_hash,
                    "cover": f"/covers/{book_id}.jpg",
                }
            }

    monkeypatch.setattr("on1y.books.preview.ZlibEapiClient", lambda _s: FakeClient())

    result = preview_ebook_candidates(
        1,
        hints=EditionHints(title="国富论", author="亚当·斯密", translator="唐日松"),
    )
    assert result["source"] == "zlib"
    assert len(result["candidates"]) == 3
    assert result["candidates"][0]["title"] == "Book 1"
    assert result["format_filter"] is None
    assert result["format_filters"] == []


def test_preview_top_three_per_checked_format(monkeypatch):
    from on1y.books.edition_match import EditionHints
    from on1y.books.preview import preview_ebook_candidates
    from on1y.books.settings_store import BookSettings
    from on1y.books.zlib_session import ZlibSession

    session = ZlibSession(host="zh.z-lib.help", remix_userid="1", remix_userkey="abc")
    monkeypatch.setattr("on1y.books.preview.load_zlib_session", lambda _uid: session)

    class FakeClient:
        def verify(self):
            return True

        def search_popular(self, query, fmt=None, *, limit=3):
            assert limit == 3
            ext = fmt or "any"
            return [
                {
                    "id": f"{ext}-{i}",
                    "hash": f"h{i}",
                    "title": f"{ext} Book {i}",
                    "extension": ext if ext != "any" else "epub",
                }
                for i in range(1, 4)
            ]

        def book_detail(self, book_id, book_hash):
            return {"book": {"cover": f"/covers/{book_id}.jpg"}}

    monkeypatch.setattr("on1y.books.preview.ZlibEapiClient", lambda _s: FakeClient())

    settings = BookSettings(format_filters=["epub", "pdf", "mobi"])
    result = preview_ebook_candidates(
        1,
        hints=EditionHints(title="国富论", author="亚当·斯密"),
        settings=settings,
    )
    assert result["format_filters"] == ["epub", "pdf", "mobi"]
    assert len(result["candidates"]) == 9
    formats = {c["format"] for c in result["candidates"]}
    assert formats == {"epub", "pdf", "mobi"}


def test_preview_fetches_zlib_cover_per_candidate(monkeypatch):
    from on1y.books.edition_match import EditionHints
    from on1y.books.preview import preview_ebook_candidates
    from on1y.books.zlib_session import ZlibSession

    session = ZlibSession(host="zh.z-lib.help", remix_userid="1", remix_userkey="abc")
    monkeypatch.setattr("on1y.books.preview.load_zlib_session", lambda _uid: session)

    class FakeClient:
        def verify(self):
            return True

        def search_popular(self, query, fmt=None, *, limit=3):
            return [{"id": 1, "hash": "h1", "title": "道德情操论", "extension": "pdf"}]

        def book_detail(self, book_id, book_hash):
            assert book_id == 1
            assert book_hash == "h1"
            return {"book": {"cover": "/img/covers/moral.jpg"}}

    monkeypatch.setattr("on1y.books.preview.ZlibEapiClient", lambda _s: FakeClient())

    result = preview_ebook_candidates(
        1,
        hints=EditionHints(title="道德情操论", author="亚当·斯密"),
        douban_cover_url="https://img1.doubanio.com/view/subject/s/public/s1.jpg",
    )
    assert result["douban"]["cover_url"].endswith("s1.jpg")
    assert result["candidates"][0]["cover_url"] == "https://zh.z-lib.help/img/covers/moral.jpg"
