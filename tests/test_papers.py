"""Paper library, API, and shared-feed integration tests."""

from __future__ import annotations


def test_paper_crud_and_knowledge_shadow(storage) -> None:
    from on1y.auth.context import user_context
    from on1y.papers.knowledge_sync import prepare_paper, sync_paper_tags
    from on1y.papers.models import PaperAuthor, PaperCreate, PaperUpdate
    from on1y.papers.shelf import create_paper, get_paper, list_papers, update_paper

    with user_context(1):
        item = create_paper(
            storage,
            1,
            PaperCreate(
                title="Attention Is All You Need",
                authors=[PaperAuthor(name="Ashish Vaswani")],
                abstract="A new network architecture based solely on attention mechanisms.",
                year=2017,
                venue="NeurIPS",
                doi="10.5555/3295222.3295349",
            ),
        )
        item = prepare_paper(storage, 1, item)
        assert item.raw_id is not None
        assert storage.count_collection_items("feed") == 0

        item = update_paper(storage, 1, item.id, PaperUpdate(status="reading", importance=4))
        assert item is not None
        assert item.status == "reading"
        assert item.importance == 4

        item = sync_paper_tags(storage, 1, item.id, ["AI", "Transformer"])
        assert item is not None
        assert set(item.tags) == {"AI", "Transformer"}
        assert list_papers(storage, 1, query="Vaswani")[0].id == item.id
        assert get_paper(storage, 1, item.id) is not None


def test_paper_author_google_scholar_links() -> None:
    from on1y.papers.models import PaperAuthor, PaperCreate, PaperItem, paper_dump

    searched = PaperAuthor(name="Geoffrey Hinton")
    assert "scholar.google.com/scholar" in searched.google_scholar_url
    profiled = PaperAuthor(name="Example", scholar_id="abc123")
    assert "citations?user=abc123" in profiled.google_scholar_url

    item = PaperItem(
        id=1,
        title="A paper",
        authors=[searched],
        status="to_read",
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )
    dumped = paper_dump(item)
    assert dumped["google_scholar_url"].endswith("A+paper")
    assert dumped["authors"][0]["google_scholar_url"] == searched.google_scholar_url
    assert dumped["zotero_reader_url"] is None

    zotero_item = item.model_copy(
        update={
            "zotero_attachment_key": "PDF123",
            "zotero_library_id": "42",
            "zotero_library_type": "groups",
        }
    )
    assert paper_dump(zotero_item)["zotero_reader_url"] == (
        "zotero://open-pdf/groups/42/items/PDF123"
    )

    coerced = PaperCreate(title="Strings work", authors=["Ada Lovelace"])  # type: ignore[list-item]
    assert coerced.authors[0].name == "Ada Lovelace"


def test_papers_api_roundtrip(storage, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setattr("on1y.adapters.sqlite_storage.get_storage", lambda: storage)
    from on1y.web.app import create_app

    client = TestClient(create_app())
    created = client.post(
        "/api/papers",
        json={
            "title": "Reliable Paper Modules",
            "authors": [{"name": "Ada Lovelace"}],
            "abstract": "An integration test.",
            "tags": ["testing"],
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["authors"][0]["google_scholar_url"].startswith("https://scholar.google.com/")

    listing = client.get("/api/papers", params={"query": "Ada"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    item_id = payload["id"]
    updated = client.patch(f"/api/papers/{item_id}", json={"status": "read", "importance": 5})
    assert updated.status_code == 200
    assert updated.json()["status"] == "read"
    assert client.get(f"/api/papers/item/{item_id}").status_code == 200
    assert client.delete(f"/api/papers/{item_id}").json() == {"ok": True}


def test_zotero_item_mapping() -> None:
    from on1y.papers.zotero import _authors, _tags, _venue, _year

    data = {
        "creators": [
            {"creatorType": "author", "firstName": "Grace", "lastName": "Hopper"},
            {"creatorType": "editor", "name": "Ignored"},
        ],
        "publicationTitle": "Communications of the ACM",
        "date": "1952-06",
        "tags": [{"tag": "compilers"}],
    }
    assert [author.name for author in _authors(data)] == ["Grace Hopper"]
    assert _venue(data) == "Communications of the ACM"
    assert _year(data["date"]) == 1952
    assert _tags(data) == ["compilers"]


def test_paper_pdf_open_settings_roundtrip(tmp_path, monkeypatch) -> None:
    from on1y.papers.settings_store import (
        PaperSettings,
        load_paper_settings,
        save_paper_settings,
    )

    path = tmp_path / "paper-settings.json"
    monkeypatch.setattr(
        "on1y.papers.settings_store.paper_settings_path",
        lambda _uid: path,
    )

    defaults = PaperSettings()
    assert defaults.pdf_open_mode == "zotero"
    assert defaults.pdf_application_path is None

    selected = PaperSettings(
        pdf_open_mode="custom",
        pdf_application_path=r"C:\Program Files\Reader\reader.exe",
    )
    save_paper_settings(1, selected)
    loaded = load_paper_settings(1)
    assert loaded.pdf_open_mode == "custom"
    assert loaded.pdf_application_path == selected.pdf_application_path


def test_zotero_local_pdf_copy(tmp_path) -> None:
    from on1y.papers.settings_store import PaperSettings
    from on1y.papers.zotero import _download_pdf

    source = tmp_path / "zotero-source.pdf"
    source.write_bytes(b"%PDF-1.7\nlocal zotero")
    cache = tmp_path / "cache"

    class Response:
        def __init__(self, *, payload=None, text="") -> None:
            self.payload = payload
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self.payload

    class Client:
        def get(self, url, params=None):
            if url.endswith("/children"):
                return Response(
                    payload=[
                        {
                            "key": "PDF123",
                            "data": {
                                "contentType": "application/pdf",
                                "filename": "paper.pdf",
                            },
                        }
                    ]
                )
            assert url.endswith("/items/PDF123/file/view/url")
            return Response(text=source.as_uri())

    settings = PaperSettings(cache_dir=str(cache), zotero_mode="local")
    copied = _download_pdf(Client(), settings, 1, "A Paper", "Paper title")
    assert copied is not None
    assert (cache / "Paper title.pdf").read_bytes().startswith(b"%PDF-")


def test_zotero_item_pagination() -> None:
    from on1y.papers.zotero import _fetch_items

    class Response:
        def __init__(self, payload) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self.payload

    class Client:
        starts: list[int] = []

        def get(self, _url, params):
            self.starts.append(params["start"])
            count = 100 if params["start"] == 0 else 1
            return Response([{"key": f"K{params['start'] + index}"} for index in range(count)])

    client = Client()
    rows = _fetch_items(client, "http://localhost/items")
    assert len(rows) == 101
    assert client.starts == [0, 100]


def test_zotero_merges_existing_local_paper(storage, monkeypatch) -> None:
    from on1y.auth.context import user_context
    from on1y.papers.models import PaperAuthor, PaperCreate, PaperUpdate
    from on1y.papers.settings_store import PaperSettings
    from on1y.papers.shelf import count_papers, create_paper, get_paper, update_paper
    from on1y.papers.zotero import sync_zotero

    local = create_paper(
        storage,
        1,
        PaperCreate(
            title="Attention Is All You Need",
            authors=[PaperAuthor(name="Ashish Vaswani")],
            status="reading",
            pdf_path="D:/papers/attention.pdf",
            tags=["local-note"],
        ),
    )
    update_paper(storage, 1, local.id, PaperUpdate(importance=5, user_note_html="keep me"))

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [
                {
                    "key": "ZOTERO1",
                    "version": 9,
                    "data": {
                        "itemType": "journalArticle",
                        "title": "Attention-Is-All-You-Need",
                        "creators": [
                            {
                                "creatorType": "author",
                                "firstName": "Ashish",
                                "lastName": "Vaswani",
                            }
                        ],
                        "date": "2017",
                        "DOI": "https://doi.org/10.5555/example",
                        "tags": [{"tag": "transformer"}],
                    },
                }
            ]

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, _url, params=None):
            if _url.endswith("/children"):
                return (
                    Response()
                    if False
                    else type(
                        "ChildResponse",
                        (),
                        {
                            "raise_for_status": lambda self: None,
                            "json": lambda self: [
                                {
                                    "key": "PDF456",
                                    "data": {
                                        "contentType": "application/pdf",
                                        "filename": "attention.pdf",
                                    },
                                }
                            ],
                        },
                    )()
                )
            assert params is not None
            return Response()

    monkeypatch.setattr("on1y.papers.zotero.httpx.Client", Client)
    with user_context(1):
        result = sync_zotero(
            storage,
            1,
            PaperSettings(zotero_enabled=True, zotero_download_pdfs=False),
        )

    assert result["imported"] == 0
    assert result["updated"] == 1
    assert count_papers(storage, 1) == 1
    merged = get_paper(storage, 1, local.id)
    assert merged is not None
    assert merged.zotero_key == "ZOTERO1"
    assert merged.zotero_attachment_key == "PDF456"
    assert merged.zotero_library_type == "users"
    assert merged.pdf_path == "D:/papers/attention.pdf"
    assert merged.status == "reading"
    assert merged.importance == 5
    assert merged.user_note_html == "keep me"
    assert set(merged.tags) == {"local-note", "transformer"}


def test_paper_matcher_normalizes_doi_and_rejects_conflicting_authors(storage) -> None:
    from on1y.papers.models import PaperAuthor, PaperCreate
    from on1y.papers.shelf import create_paper, find_matching_paper

    paper = create_paper(
        storage,
        1,
        PaperCreate(
            title="A Unified Paper System",
            authors=[PaperAuthor(name="Ada Lovelace")],
            year=2026,
            doi="DOI: 10.1000/ABC.123",
        ),
    )
    by_doi = find_matching_paper(storage, 1, doi="https://doi.org/10.1000/abc.123")
    assert by_doi is not None and by_doi.id == paper.id

    conflict = find_matching_paper(
        storage,
        1,
        title="A-Unified_Paper System.pdf",
        year=2026,
        authors=[PaperAuthor(name="Grace Hopper")],
    )
    assert conflict is None


def test_paper_schema_v22_upgrade_preserves_existing_data(tmp_path) -> None:
    import sqlite3

    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.papers.models import PaperCreate
    from on1y.papers.shelf import create_paper, list_papers

    db_path = tmp_path / "paper-v21-upgrade.db"
    initial = SqliteStorage(db_path)
    initial.initialize()
    create_paper(
        initial,
        1,
        PaperCreate(title="Preserved Paper", tags=["migration", "zotero"]),
    )
    initial.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE paper_items DROP COLUMN zotero_attachment_key")
        conn.execute("ALTER TABLE paper_items DROP COLUMN zotero_library_type")
        conn.execute("DELETE FROM schema_migrations WHERE version = 22")

    upgraded = SqliteStorage(db_path)
    upgraded.initialize()
    try:
        columns = {
            str(row[1]) for row in upgraded._connect().execute("PRAGMA table_info(paper_items)")
        }
        items = list_papers(upgraded, 1)
        assert {"zotero_attachment_key", "zotero_library_type"} <= columns
        assert len(items) == 1
        assert items[0].title == "Preserved Paper"
        assert items[0].tags == ["migration", "zotero"]
    finally:
        upgraded.close()
