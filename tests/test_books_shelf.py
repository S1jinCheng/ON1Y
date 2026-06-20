def test_parse_cached_path():
    from on1y.books.models import parse_cached_path

    assert parse_cached_path("cached: D:\\books\\国富论.pdf\nsource: zlib") == "D:\\books\\国富论.pdf"
    assert parse_cached_path(None) is None


def test_related_shelf_books_by_tags(monkeypatch):
    import tempfile
    from pathlib import Path

    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.books.models import BookLink, BookShelfCreate
    from on1y.books.recommend import find_related_shelf_books
    from on1y.books.shelf import create_shelf_item

    db = Path(tempfile.mkdtemp()) / "test.db"
    storage = SqliteStorage(db)
    storage.initialize()
    monkeypatch.setattr("on1y.user.accounts.bootstrap_default_user", lambda _s: None)

    link = BookLink(label="豆瓣", url="https://book.douban.com/subject/1/")
    a = create_shelf_item(
        storage,
        1,
        BookShelfCreate(
            title="国富论",
            author="亚当·斯密",
            summary="经济学经典",
            links=[link],
            tags=["经济学", "经典"],
        ),
    )
    create_shelf_item(
        storage,
        1,
        BookShelfCreate(
            title="资本论",
            author="马克思",
            summary="政治经济学",
            links=[link],
            tags=["经济学"],
        ),
    )
    related = find_related_shelf_books(storage, 1, a.id, limit=3)
    assert len(related) == 1
    assert related[0]["title"] == "资本论"
