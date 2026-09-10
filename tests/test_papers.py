"""Paper library, API, and shared-feed integration tests."""

from __future__ import annotations


def test_paper_crud_and_knowledge_shadow(storage) -> None:
    from on1y.auth.context import user_context
    from on1y.papers.knowledge_sync import prepare_paper, sync_paper_tags
    from on1y.papers.models import PaperAuthor, PaperCollection, PaperCreate, PaperUpdate
    from on1y.papers.shelf import (
        create_paper,
        get_paper,
        list_paper_collections,
        list_papers,
        update_paper,
    )

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
                zotero_collections=[
                    PaperCollection(key="TRANSFORMERS", name="Transformer", path="AI / Transformer")
                ],
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
        assert list_papers(storage, 1, collection_key="TRANSFORMERS")[0].id == item.id
        assert list_papers(storage, 1, collection_key="MISSING") == []
        assert list_paper_collections(storage, 1)[0]["paper_count"] == 1
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


def test_zotero_collection_hierarchy_and_multiple_memberships() -> None:
    from on1y.papers.zotero import _collection_index, _collections_for_item

    index = _collection_index(
        [
            {"key": "ROOT", "data": {"name": "机器学习", "parentCollection": False}},
            {"key": "CHILD", "data": {"name": "Transformer", "parentCollection": "ROOT"}},
            {"key": "OTHER", "data": {"name": "待读", "parentCollection": False}},
        ]
    )
    assert index["CHILD"].path == "机器学习 / Transformer"
    memberships = _collections_for_item(
        {"collections": ["OTHER", "CHILD", "CHILD"]},
        index,
    )
    assert {row.key for row in memberships} == {"CHILD", "OTHER"}
    assert next(row for row in memberships if row.key == "CHILD").parent_key == "ROOT"


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
    assert defaults.ai_summary_mode == "manual"
    assert defaults.pdf_open_mode == "zotero"
    assert defaults.pdf_application_path is None

    selected = PaperSettings(
        ai_summary_mode="auto",
        pdf_open_mode="custom",
        pdf_application_path=r"C:\Program Files\Reader\reader.exe",
    )
    save_paper_settings(1, selected)
    loaded = load_paper_settings(1)
    assert loaded.ai_summary_mode == "auto"
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
                        "collections": list(Client.item_collections),
                    },
                }
            ]

    class Client:
        item_collections = ["COLLECTION_CHILD"]

        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, _url, params=None):
            if _url.endswith("/collections"):
                return type(
                    "CollectionResponse",
                    (),
                    {
                        "raise_for_status": lambda self: None,
                        "json": lambda self: [
                            {
                                "key": "COLLECTION_ROOT",
                                "data": {"name": "AI", "parentCollection": False},
                            },
                            {
                                "key": "COLLECTION_CHILD",
                                "data": {
                                    "name": "Transformer",
                                    "parentCollection": "COLLECTION_ROOT",
                                },
                            },
                        ],
                    },
                )()
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
    assert [row.path for row in merged.zotero_collections] == ["AI / Transformer"]

    Client.item_collections = []
    sync_zotero(
        storage,
        1,
        PaperSettings(zotero_enabled=True, zotero_download_pdfs=False),
    )
    resynced = get_paper(storage, 1, local.id)
    assert resynced is not None
    assert resynced.zotero_collections == []
    assert count_papers(storage, 1) == 1


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
        conn.execute("ALTER TABLE paper_items DROP COLUMN ai_summary_json")
        conn.execute("ALTER TABLE paper_items DROP COLUMN ai_summary_status")
        conn.execute("ALTER TABLE paper_items DROP COLUMN ai_summary_error")
        conn.execute("ALTER TABLE paper_items DROP COLUMN ai_summary_model")
        conn.execute("ALTER TABLE paper_items DROP COLUMN ai_summary_updated_at")
        conn.execute("ALTER TABLE paper_items DROP COLUMN figures_json")
        conn.execute("ALTER TABLE paper_items DROP COLUMN zotero_collections_json")
        conn.execute("DELETE FROM schema_migrations WHERE version >= 22")

    upgraded = SqliteStorage(db_path)
    upgraded.initialize()
    try:
        columns = {
            str(row[1]) for row in upgraded._connect().execute("PRAGMA table_info(paper_items)")
        }
        items = list_papers(upgraded, 1)
        assert {
            "zotero_attachment_key",
            "zotero_library_type",
            "ai_summary_json",
            "figures_json",
            "zotero_collections_json",
        } <= columns
        assert len(items) == 1
        assert items[0].title == "Preserved Paper"
        assert items[0].tags == ["migration", "zotero"]
    finally:
        upgraded.close()

def test_paper_note_syncs_to_notes_collection(storage, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setattr("on1y.adapters.sqlite_storage.get_storage", lambda: storage)
    from on1y.web.app import create_app

    client = TestClient(create_app())
    created = client.post("/api/papers", json={"title": "Paper note bridge"})
    assert created.status_code == 200
    item = created.json()

    saved = client.patch(
        f"/api/papers/{item['id']}",
        json={"user_note_html": "<p>experiment note</p>"},
    )
    assert saved.status_code == 200
    raw = storage.get_raw_by_id(item["raw_id"])
    assert raw is not None
    assert raw.source_meta["user_note_html"] == "<p>experiment note</p>"
    from on1y.auth.context import user_context

    with user_context(1):
        assert storage.count_collection_items("notes") == 1

    cleared = client.patch(
        f"/api/papers/{item['id']}",
        json={"user_note_html": ""},
    )
    assert cleared.status_code == 200
    assert storage.count_collection_items("notes") == 0


def test_paper_figure_endpoint_supports_inline_preview_and_download(
    storage, tmp_path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient
    from on1y.papers.models import PaperCreate
    from on1y.papers.shelf import create_paper
    from on1y.utils.json_util import dumps_json

    paper = create_paper(storage, 1, PaperCreate(title="Figure viewer"))
    figure_path = tmp_path / "figure-01.png"
    figure_path.write_bytes(b"\x89PNG\r\n\x1a\npreview")
    storage._connect().execute(
        "UPDATE paper_items SET figures_json = ? WHERE id = ?",
        (
            dumps_json(
                [
                    {
                        "filename": figure_path.name,
                        "page": 2,
                        "caption": "Figure 1. Result",
                        "kind": "figure",
                        "width": 800,
                        "height": 600,
                    }
                ]
            ),
            paper.id,
        ),
    )
    storage._connect().commit()
    monkeypatch.setattr(
        "on1y.papers.summary.paper_figure_dir",
        lambda _user_id, _item_id: tmp_path,
    )
    monkeypatch.setattr("on1y.adapters.sqlite_storage.get_storage", lambda: storage)
    from on1y.web.app import create_app

    client = TestClient(create_app())
    inline = client.get(f"/api/papers/{paper.id}/figures/{figure_path.name}")
    assert inline.status_code == 200
    assert "attachment" not in inline.headers.get("content-disposition", "")
    download = client.get(
        f"/api/papers/{paper.id}/figures/{figure_path.name}",
        params={"download": "1"},
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

def test_extract_paper_pdf_text_and_figure(tmp_path) -> None:
    import pymupdf
    from on1y.papers.summary import extract_paper_pdf

    pdf_path = tmp_path / "figure-paper.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "A Reliable Evaluation")
    page.draw_rect(pymupdf.Rect(90, 180, 500, 420), color=(0, 0, 0), fill=(0.9, 0.95, 1))
    page.insert_text((110, 250), "Accuracy: 92% vs 80%")
    page.insert_text((90, 450), "Figure 1. Accuracy improves by 12 percentage points.")
    page.insert_text((72, 520), "Results show a substantial improvement over the baseline.")
    document.save(pdf_path)
    document.close()

    text, figures = extract_paper_pdf(pdf_path, tmp_path / "figures")
    assert "substantial improvement" in text
    assert figures
    assert figures[0].page == 1
    assert (tmp_path / "figures" / figures[0].filename).is_file()


def test_extract_paper_figures_respects_columns_and_tables(tmp_path) -> None:
    import pymupdf
    from on1y.papers.summary import extract_paper_pdf

    pdf_path = tmp_path / "layout-paper.pdf"
    document = pymupdf.open()
    figure_page = document.new_page()
    figure_page.insert_text((55, 155), "This paragraph belongs to the left column.")
    figure_page.insert_text((55, 175), "It must not appear inside the figure crop.")
    figure_page.draw_rect(
        pymupdf.Rect(325, 130, 545, 330),
        color=(0.15, 0.25, 0.45),
        fill=(0.9, 0.95, 1),
    )
    figure_page.draw_line((350, 295), (510, 175), color=(0.1, 0.4, 0.8), width=3)
    figure_page.insert_text((350, 190), "Accuracy +12%")
    figure_page.insert_text((325, 355), "Figure 1. Evaluation on the held-out test set.")

    table_page = document.new_page()
    table_page.insert_text((60, 90), "Table 1. Main benchmark results.")
    for x in (60, 220, 380, 535):
        table_page.draw_line((x, 120), (x, 300), color=(0, 0, 0))
    for y in (120, 165, 210, 255, 300):
        table_page.draw_line((60, y), (535, y), color=(0, 0, 0))
    table_page.insert_text((80, 150), "Model")
    table_page.insert_text((245, 150), "Accuracy")
    table_page.insert_text((405, 150), "Latency")
    table_page.insert_text((60, 340), "This paragraph follows the table and must stay outside.")
    document.save(pdf_path)
    document.close()

    text, figures = extract_paper_pdf(pdf_path, tmp_path / "layout-figures")
    assert "left column" in text
    assert [figure.kind for figure in figures] == ["figure", "table"]
    assert all(figure.width and figure.height for figure in figures)
    assert figures[0].width is not None and figures[0].width < 700
    assert figures[1].width is not None and figures[1].width > 900

def test_generate_paper_summary_updates_tags_and_search_body(
    storage, tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from on1y.auth.context import user_context
    from on1y.papers.models import PaperCreate, PaperFigure
    from on1y.papers.shelf import create_paper
    from on1y.papers.summary import generate_paper_summary

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    paper = create_paper(
        storage,
        1,
        PaperCreate(title="Efficient Models", pdf_path=str(pdf_path), tags=["existing"]),
    )

    class Client:
        def chat_json(self, *_args, **_kwargs):
            return {
                "overview": "研究提出了更高效的模型，并在基准上获得提升。",
                "research_question": "如何降低计算成本？",
                "method": "采用稀疏结构并进行对照实验。",
                "key_findings": ["计算量下降"],
                "effects": ["准确率由 80% 提升至 92%"],
                "limitations": ["只测试了一个数据集"],
                "keywords": ["效率", "existing"],
            }

    monkeypatch.setattr(
        "on1y.papers.summary.extract_paper_pdf",
        lambda *_args, **_kwargs: (
            "Introduction. Results: accuracy improved from 80% to 92%. Conclusion.",
            [PaperFigure(filename="figure-01.png", page=2, caption="Figure 1. Results")],
        ),
    )
    monkeypatch.setattr("on1y.papers.summary.get_llm_client", lambda: Client())
    monkeypatch.setattr(
        "on1y.papers.summary.resolve_llm_settings",
        lambda **_kwargs: SimpleNamespace(model="test-model"),
    )

    with user_context(1):
        summarized = generate_paper_summary(storage, 1, paper.id)

    assert summarized.ai_summary is not None
    assert summarized.ai_summary.effects == ["准确率由 80% 提升至 92%"]
    assert summarized.ai_summary_status == "ok"
    assert summarized.ai_summary_model == "test-model"
    assert summarized.tags == ["existing", "效率"]
    assert len(summarized.figures) == 1
    raw = storage.get_raw_by_id(summarized.raw_id)
    assert raw is not None
    assert "accuracy improved" in raw.body_text
