"""Tests for books module."""

from __future__ import annotations

from unittest.mock import patch

from on1y.books.models import BookLink, BookShelfCreate, BookSource, BookSourcesFile
from on1y.books.providers.parsers.douban_book import (
    _edition_from_item,
    _parse_search_data,
    _parse_short_reviews,
)
from on1y.books.search import search_books


def test_default_sources_contain_builtins():
    from on1y.books.builtin_sources import builtin_sources

    ids = {s.id for s in builtin_sources()}
    assert ids == {"douban-fetch", "zlib-link", "annas-link"}
    douban = next(s for s in builtin_sources() if s.id == "douban-fetch")
    assert douban.type == "fetch"


def test_parse_douban_search_json():
    html = """
    <script>
    window.__DATA__ = {"count": 1, "items": [{
      "title": "国富论",
      "url": "https://book.douban.com/subject/1261560/",
      "id": 1261560,
      "abstract": "[英] 亚当·斯密 / 郭大力 等 / 华夏出版社 / 2005-1 / 69.00元",
      "cover_url": "https://img1.doubanio.com/view/subject/m/public/s2164670.jpg",
      "rating": {"value": 9.0, "count": 12000}
    }]}
    </script>
    """
    items = _parse_search_data(html)
    assert len(items) == 1
    edition = _edition_from_item(items[0])
    assert edition is not None
    assert edition.title == "国富论"
    assert edition.author is not None
    assert edition.translator is not None
    assert edition.rating == 9.0


def test_link_search_with_mock_douban():
    payload = BookSourcesFile(
        sources=[
            BookSource(
                id="douban-fetch",
                name="豆瓣图书",
                type="fetch",
                parser="douban_book",
                enabled=True,
                url_template="https://search.douban.com/book/subject_search?search_text={query}",
                sort_order=0,
            )
        ]
    )
    fake = [
        __import__("on1y.books.models", fromlist=["BookEditionHit"]).BookEditionHit(
            edition_id="douban:1",
            source_id="douban-fetch",
            source_name="豆瓣图书",
            title="Test",
            url="https://book.douban.com/subject/1/",
        )
    ]
    with patch("on1y.books.search.list_enabled_sources", return_value=payload.sources):
        with patch("on1y.books.search.search_douban_books", return_value=fake):
            editions, links = search_books(1, "wealth")
    assert len(editions) == 1
    assert editions[0].title == "Test"
    assert links == []


def test_parse_short_reviews_from_html():
    html = """
    <div id="score" class="comment-list">
      <li class="comment-item">
        <div class="comment">
          <h3>
            <span class="comment-info">
              <a href="https://www.douban.com/people/reader/">读者甲</a>
              <a class="comment-time">2020-01-01 12:00:00</a>
            </span>
          </h3>
          <p class="comment-content"><span class="short">这是一本很好的书，值得一读。(展开)</span></p>
        </div>
      </li>
    </div>
    """
    from bs4 import BeautifulSoup

    reviews = _parse_short_reviews(BeautifulSoup(html, "html.parser"))
    assert len(reviews) == 1
    assert reviews[0].author == "读者甲"
    assert "值得一读" in reviews[0].content
    assert "(展开)" not in reviews[0].content


def test_list_cached_ebooks_from_notes(monkeypatch):
    import tempfile
    from pathlib import Path

    from on1y.books.cache_files import list_cached_ebooks
    from on1y.books.settings_store import BookSettings

    base = Path(tempfile.mkdtemp())
    cache = base / "cache"
    cache.mkdir()
    epub = cache / "国富论.epub"
    epub.write_bytes(b"x" * 2048)
    monkeypatch.setattr(
        "on1y.books.cache_files.load_book_settings",
        lambda _uid: BookSettings(cache_dir=str(cache)),
    )
    monkeypatch.setattr(
        "on1y.books.cache_files.resolve_books_cache_dir",
        lambda _uid, _override: cache,
    )
    files = list_cached_ebooks(1, "国富论", notes=f"cached: {epub}")
    assert len(files) == 1
    assert files[0]["format"] == "epub"


def test_book_shelf_create_model_requires_link():
    item = BookShelfCreate(
        title="Test Book",
        links=[BookLink(label="Douban", url="https://book.douban.com/subject/1/")],
    )
    assert item.status == "reading"


def test_zlib_search_url_includes_translator():
    from on1y.books.zlib_links import edition_search_query, zlib_general_search_url
    from urllib.parse import unquote

    query = edition_search_query("国富论", author="亚当·斯密", translator="唐日松")
    assert query == "国富论 亚当·斯密 唐日松"
    url = zlib_general_search_url(query)
    assert "/s/" in url
    path = unquote(url.split("/s/", 1)[1])
    assert "唐日松" in path


def test_annas_search_url_uses_tw_mirror():
    from on1y.books.zlib_links import annas_search_url

    url = annas_search_url("国富论", translator="唐日松")
    assert url.startswith("https://tw.annas-archive.gl/search?")
    assert "唐日松" in url or "%" in url


def test_zlib_search_url_and_edition_links():
    from on1y.books.zlib_links import build_edition_links, zlib_search_url

    url = zlib_search_url("国富论", "epub")
    assert url.startswith("https://zh.z-lib.help/s/")
    assert "extension=epub" in url
    links = build_edition_links(
        title="国富论",
        douban_url="https://book.douban.com/subject/1261560/",
    )
    labels = [link.label for link in links]
    assert labels == ["豆瓣", "EPUB", "PDF", "MOBI", "安娜档案"]
    assert links[0].url.endswith("/subject/1261560/")


def test_book_settings_roundtrip(monkeypatch):
    import tempfile
    from pathlib import Path

    from on1y.books.settings_store import BookSettings, load_book_settings, save_book_settings

    base = Path(tempfile.mkdtemp())
    path = base / "settings.json"
    monkeypatch.setattr(
        "on1y.books.settings_store.user_books_settings_path",
        lambda _uid: path,
    )
    settings = BookSettings(cache_dir=str(base / "books-cache"), preferred_format="pdf")
    save_book_settings(1, settings)
    loaded = load_book_settings(1)
    assert loaded.cache_dir == str(base / "books-cache")
    assert loaded.preferred_format == "pdf"
    assert loaded.zlib_base_url == "https://zh.z-lib.help"


def test_load_book_sources_migrates_openlibrary_away(monkeypatch):
    import json
    import tempfile
    from pathlib import Path

    from on1y.books.models import BookSource, BookSourcesFile
    from on1y.books.sources_store import load_book_sources, save_book_sources

    base = Path(tempfile.mkdtemp())
    path = base / "sources.json"
    monkeypatch.setattr("on1y.books.sources_store.user_books_sources_path", lambda _uid: path)
    save_book_sources(
        1,
        BookSourcesFile(
            sources=[
                BookSource(
                    id="douban-link",
                    name="豆瓣",
                    type="link",
                    enabled=True,
                    url_template="https://search.douban.com/book/subject_search?search_text={query}",
                    sort_order=0,
                ),
                BookSource(
                    id="openlibrary-link",
                    name="Open Library",
                    type="link",
                    enabled=True,
                    url_template="https://openlibrary.org/search?q={query}",
                    sort_order=1,
                ),
            ],
        ),
    )
    loaded = load_book_sources(1)
    ids = {s.id for s in loaded.sources}
    assert ids == {"douban-fetch", "zlib-link", "annas-link"}
    assert "openlibrary-link" not in ids
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "openlibrary-link" not in {s["id"] for s in on_disk["sources"]}
