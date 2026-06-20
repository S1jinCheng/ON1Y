def test_download_ebook_prefers_zlib(monkeypatch):
    from on1y.books.download import download_ebook_bytes
    from on1y.books.edition_match import EditionHints
    from on1y.books.settings_store import BookSettings
    from on1y.books.zlib_session import ZlibSession

    session = ZlibSession(host="zh.z-lib.help", remix_userid="1", remix_userkey="abc")
    monkeypatch.setattr("on1y.books.download.load_zlib_session", lambda _uid: session)
    monkeypatch.setattr(
        "on1y.books.download.download_from_zlib_eapi",
        lambda *_a, **_k: (b"%PDF-" + b"x" * 2040, {"format": "pdf"}),
    )

    settings = BookSettings()
    data, source, meta = download_ebook_bytes(
        1,
        hints=EditionHints(title="国富论"),
        fmt=None,
        settings=settings,
    )
    assert source == "zlib"
    assert len(data) == 2045
    assert meta["format"] == "pdf"


def test_download_ebook_falls_back_to_annas(monkeypatch):
    from on1y.books.download import download_ebook_bytes
    from on1y.books.edition_match import EditionHints
    from on1y.books.settings_store import BookSettings

    monkeypatch.setattr("on1y.books.download.load_zlib_session", lambda _uid: None)
    monkeypatch.setattr(
        "on1y.books.download.download_from_annas",
        lambda **_k: (b"PK\x03\x04" + b"y" * 2040, {"format": "epub"}),
    )

    data, source, meta = download_ebook_bytes(
        1,
        hints=EditionHints(title="国富论"),
        fmt=None,
        settings=BookSettings(),
    )
    assert source == "annas"
    assert len(data) >= 2044
    assert meta["format"] == "epub"


def test_zlib_eapi_search_first_parses_books(monkeypatch):
    from on1y.books.zlib_eapi import ZlibEapiClient
    from on1y.books.zlib_session import ZlibSession

    session = ZlibSession(host="1lib.sk", remix_userid="9", remix_userkey="key")
    client = ZlibEapiClient(session)

    def fake_request(method, path, *, data=None, params=None):
        assert method == "POST"
        assert path == "/eapi/book/search"
        assert data is not None
        assert data.get("order") == "popular"
        return {"success": True, "books": [{"id": 12, "hash": "abcd", "title": "Test", "extension": "epub"}]}

    monkeypatch.setattr(client, "_request", fake_request)
    book = client.search_first("Test", "epub")
    assert book is not None
    assert book["id"] == 12
