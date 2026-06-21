def test_send_shelf_book_to_kindle_uses_cached_path(monkeypatch, tmp_path):
    from on1y.books.acquire import send_shelf_book_to_kindle
    from on1y.books.models import BookLink, BookShelfItem

    book_file = tmp_path / "test.pdf"
    book_file.write_bytes(b"%PDF-" + b"x" * 2040)

    item = BookShelfItem(
        id=7,
        title="国富论",
        author="[英]亚当·斯密",
        translator="胡长明",
        publisher="人民日报出版社",
        links=[BookLink(label="豆瓣", url="https://book.douban.com/subject/1/")],
        notes=f"cached: {book_file}\nsource: zlib",
        cached_format="pdf",
        local_path=str(book_file),
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )

    captured: dict[str, str] = {}

    class FakeStorage:
        pass

    def _capture_kindle(_uid, path, *, title):
        captured["title"] = title
        return True, "sent", None

    def _fake_update(_storage, _uid, _item_id, payload):
        return item.model_copy(update={"notes": payload.notes})

    monkeypatch.setattr("on1y.books.shelf.get_shelf_item", lambda _s, _u, _id: item)
    monkeypatch.setattr("on1y.books.acquire.maybe_send_kindle", _capture_kindle)
    monkeypatch.setattr("on1y.books.shelf.update_shelf_item", _fake_update)

    result = send_shelf_book_to_kindle(1, FakeStorage(), 7)
    assert result["kindle_sent"] is True
    assert result["kindle_status"] == "sent"
    assert result["shelf_item"] is not None
    assert "kindle_status: sent" in (result["shelf_item"]["notes"] or "")
    assert captured["title"] == "国富论 [英]亚当·斯密 著;胡长明 译 人民日报出版社"


def test_send_shelf_book_to_kindle_missing_file(monkeypatch):
    from on1y.books.acquire import send_shelf_book_to_kindle
    from on1y.books.models import BookLink, BookShelfItem
    from on1y.exceptions import ConfigurationError

    item = BookShelfItem(
        id=8,
        title="无文件",
        links=[BookLink(label="豆瓣", url="https://book.douban.com/subject/2/")],
        notes="source: zlib",
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )

    monkeypatch.setattr("on1y.books.shelf.get_shelf_item", lambda _s, _u, _id: item)
    monkeypatch.setattr("on1y.books.cache_files.list_cached_ebooks", lambda *_a, **_k: [])

    try:
        send_shelf_book_to_kindle(1, object(), 8)
        raise AssertionError("expected ConfigurationError")
    except ConfigurationError as exc:
        assert "未找到本地缓存" in str(exc)
