from pathlib import Path

import pymupdf
from on1y.papers.literature import LiteratureVault, normalize_arxiv, normalize_doi
from on1y.papers.settings_store import PaperSettings, paper_settings_public_view
from on1y.papers.translation import (
    BabelDocSubprocessAdapter,
    LocalTranslationGateway,
    flatten_pdf_visual_regions,
    next_bilingual_path,
)


def make_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Test paper")
    document.save(path)
    document.close()


def test_identifier_normalization() -> None:
    assert normalize_doi("https://doi.org/10.1145/ABC.1?x=1") == "10.1145/abc.1"
    assert normalize_arxiv("https://arxiv.org/pdf/2501.01234v2.pdf") == "2501.01234"


def test_vault_batch_publish_and_feedback(tmp_path: Path) -> None:
    vault = LiteratureVault(1, tmp_path / "Literature")
    initialized = vault.initialize()
    assert Path(initialized["db_path"]).is_file()
    assert (vault.root / "_templates" / "paper-note.md").is_file()

    source = tmp_path / "source.pdf"
    make_pdf(source)
    records = [
        {
            "title": "A Human AI Paper",
            "authors": ["A. Author"],
            "year": 2026,
            "venue": "CHI",
            "doi": "https://doi.org/10.1000/TEST",
            "local_pdf_path": str(source),
            "area": "Proactive AI",
            "recommendation": "A focused recent contribution.",
        }
    ]
    validation = vault.validate(records)
    assert len(validation["accepted"]) == 1
    assert validation["duplicates"] == []

    created = vault.create_batch(
        field="Human-AI Interaction",
        field_code="HAI",
        batch_date="2026-09-20",
        records=records,
    )
    assert created["created"] is True
    batch_id = created["batch_id"]

    duplicate = vault.validate([{"title": "Different title", "doi": "doi:10.1000/test"}])
    assert len(duplicate["duplicates"]) == 1

    published = vault.publish(batch_id)
    assert published["status"] == "published"
    day = vault.root / "Human-AI-Interaction" / "2026-09-20"
    assert (day / "00-Reading-List.md").is_file()
    assert (day / "01-Venue-Guide.md").is_file()
    assert len(list((day / "Original").glob("*.pdf"))) == 1
    note = next((day / "Notes").glob("*.md"))
    text = note.read_text(encoding="utf-8")
    assert "## My Summary" not in text
    assert "## Important Points" not in text
    assert "A focused recent contribution." in (day / "00-Reading-List.md").read_text(
        encoding="utf-8"
    )

    note.write_text(
        text.replace("status: unread", "status: read").rstrip()
        + "\n\nMy own summary.\n",
        encoding="utf-8",
    )
    feedback = vault.rebuild_feedback(batch_id)
    assert feedback["read"] == 1
    assert feedback["changed_notes"] == 1
    feedback_text = Path(feedback["path"]).read_text(encoding="utf-8")
    assert "My own summary." in feedback_text
    assert "### My Summary" not in feedback_text
    again = vault.rebuild_feedback(batch_id)
    assert again["changed_notes"] == 0


def test_unavailable_pdf_does_not_block_publish(tmp_path: Path) -> None:
    vault = LiteratureVault(1, tmp_path / "Literature")
    created = vault.create_batch(
        field="Agents",
        field_code="AG",
        batch_date="2026-09-21",
        records=[{"title": "Metadata Only", "recommendation": "Important context."}],
    )
    published = vault.publish(created["batch_id"])
    assert published["status"] == "published"
    reading = (vault.root / "Agents" / "2026-09-21" / "00-Reading-List.md").read_text(
        encoding="utf-8"
    )
    assert "Full text unavailable automatically" in reading


def test_manual_reading_status_drives_progress_and_daily_plan(tmp_path: Path) -> None:
    vault = LiteratureVault(1, tmp_path / "Literature")
    created = vault.create_batch(
        field="Human-AI Interaction",
        field_code="HAI",
        batch_date="2026-09-20",
        records=[
            {"title": "Read Paper"},
            {"title": "Dismissed Paper"},
            {"title": "Carryover Paper"},
        ],
    )
    batch = vault.publish(created["batch_id"])
    vault.set_paper_statuses([batch["papers"][0]["id"]], "read")
    vault.set_paper_statuses([batch["papers"][1]["id"]], "dismissed")

    refreshed = vault.batch(created["batch_id"])
    assert refreshed is not None
    assert refreshed["progress"] == {
        "total": 3,
        "read": 1,
        "dismissed": 1,
        "pending": 1,
        "carried": 0,
    }
    notes = sorted((vault.root / "Human-AI-Interaction" / "2026-09-20" / "Notes").glob("*.md"))
    assert "status: read" in notes[0].read_text("utf-8")
    assert "status: dismissed" in notes[1].read_text("utf-8")

    plan = vault.daily_plan(target_date="2026-09-21", field="Human-AI Interaction")
    assert plan["carryover_count"] == 1
    assert plan["carryover"][0]["title"] == "Carryover Paper"
    assert plan["new_slots"] == 19
    blocked = vault.daily_plan(target_date="2026-09-21", field="Different Field")
    assert blocked["blocking_fields"] == ["Human-AI Interaction"]
    state = vault.write_reading_state()
    assert state["next"]["carryover_count"] == 1
    assert Path(state["path"]).is_file()


def test_publish_moves_and_renumbers_carryover_files_without_breaking_links(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "on1y.papers.settings_store.load_paper_settings",
        lambda _user_id: PaperSettings(translation_auto_enqueue=False),
    )
    vault = LiteratureVault(1, tmp_path / "Literature")
    first_source = tmp_path / "first.pdf"
    carried_source = tmp_path / "carried.pdf"
    new_source = tmp_path / "new.pdf"
    for source in (first_source, carried_source, new_source):
        make_pdf(source)

    first_created = vault.create_batch(
        field="Human-AI Interaction",
        field_code="HAI",
        batch_date="2026-09-20",
        records=[
            {"title": "Finished Paper", "local_pdf_path": str(first_source)},
            {"title": "Carried Paper", "local_pdf_path": str(carried_source)},
        ],
    )
    first_batch = vault.publish(first_created["batch_id"])
    finished, carried = first_batch["papers"]
    old_original = vault.root / str(carried["original_pdf_relpath"])
    old_note = vault.root / str(carried["note_relpath"])
    old_hash = old_original.read_bytes()
    old_bilingual_rel = str(carried["original_pdf_relpath"]).replace(
        "/Original/", "/Bilingual/"
    ).replace(".pdf", "_CN-EN.pdf")
    old_bilingual = vault.root / old_bilingual_rel
    make_pdf(old_bilingual)
    with vault.connect() as conn:
        conn.execute(
            "UPDATE papers SET bilingual_pdf_relpath=? WHERE id=?",
            (old_bilingual_rel, carried["id"]),
        )
        conn.commit()
    vault._update_note_pdf_links(carried["id"], bilingual_relpath=old_bilingual_rel)
    old_note.write_text(
        old_note.read_text("utf-8").rstrip()
        + f"\n\nMy partial note. [[../Bilingual/{old_bilingual.name}#page=1&selection=abc]]\n",
        "utf-8",
    )
    finished_note = vault.root / str(finished["note_relpath"])
    finished_note.write_text(
        finished_note.read_text("utf-8").rstrip()
        + f"\n\nSee [[../Bilingual/{old_bilingual.name}#page=1&selection=abc]].\n",
        "utf-8",
    )
    vault.set_paper_statuses([finished["id"]], "read")

    second_created = vault.create_batch(
        field="Human-AI Interaction",
        field_code="HAI",
        batch_date="2026-09-21",
        records=[{"title": "New Paper", "local_pdf_path": str(new_source)}],
    )
    assert second_created["carryover_count"] == 1
    second_batch = vault.publish(second_created["batch_id"])
    moved = second_batch["papers"][0]
    assert moved["id"] == carried["id"]
    assert moved["position"] == 1
    assert Path(str(moved["original_pdf_relpath"])).name.startswith("001_")
    assert Path(str(moved["bilingual_pdf_relpath"])).name.startswith("001_")
    assert Path(str(moved["note_relpath"])).name.startswith("001_")

    new_original = vault.root / str(moved["original_pdf_relpath"])
    new_bilingual = vault.root / str(moved["bilingual_pdf_relpath"])
    new_note = vault.root / str(moved["note_relpath"])
    assert new_original.read_bytes() == old_hash
    assert new_bilingual.is_file()
    assert not old_original.exists()
    assert not old_bilingual.exists()
    assert not old_note.exists()
    moved_note_text = new_note.read_text("utf-8")
    assert "paper_id: HAI-20260921-001" in moved_note_text
    assert "My partial note." in moved_note_text
    assert new_bilingual.name in moved_note_text
    assert "#page=1&selection=abc" in moved_note_text
    finished_text = finished_note.read_text("utf-8")
    assert new_bilingual.name in finished_text
    assert "#page=1&selection=abc" in finished_text
    old_reading = (
        vault.root / "Human-AI-Interaction" / "2026-09-20" / "00-Reading-List.md"
    ).read_text("utf-8")
    assert "Carried forward to 2026-09-21" in old_reading


def test_published_vault_projects_to_shelf_by_folder_and_prefers_bilingual(
    storage, tmp_path: Path
) -> None:
    from on1y.papers.literature import sync_published_to_shelf
    from on1y.papers.shelf import list_paper_folders, list_papers

    vault = LiteratureVault(1, tmp_path / "Literature")
    source = tmp_path / "source.pdf"
    make_pdf(source)
    created = vault.create_batch(
        field="Human-AI Interaction",
        field_code="HAI",
        batch_date="2026-09-20",
        records=[
            {
                "title": "Folder First Paper",
                "authors": ["A. Author"],
                "local_pdf_path": str(source),
                "area": "Mixed Initiative",
            }
        ],
    )
    batch = vault.publish(created["batch_id"])
    synced = sync_published_to_shelf(storage, 1, vault=vault)
    assert synced["created"] == 1

    papers = list_papers(
        storage,
        1,
        folder_key="vault:Human-AI-Interaction/2026-09-20",
    )
    assert len(papers) == 1
    assert papers[0].literature_paper_id == batch["papers"][0]["id"]
    assert "Original" in str(papers[0].pdf_path)
    assert [row["path"] for row in list_paper_folders(storage, 1)] == [
        "Human-AI-Interaction",
        "Human-AI-Interaction/2026-09-20",
    ]

    bilingual_rel = "Human-AI-Interaction/2026-09-20/Bilingual/001_Folder_First_Paper_CN-EN.pdf"
    bilingual = vault.root / bilingual_rel
    make_pdf(bilingual)
    with vault.connect() as conn:
        conn.execute(
            "UPDATE papers SET bilingual_pdf_relpath=? WHERE id=?",
            (bilingual_rel, batch["papers"][0]["id"]),
        )
        conn.commit()
    refreshed = sync_published_to_shelf(storage, 1, vault=vault)
    assert refreshed["updated"] == 1
    assert list_papers(storage, 1)[0].pdf_path == str(bilingual.resolve())


def test_bilingual_output_is_versioned_and_never_overwritten(tmp_path: Path) -> None:
    directory = tmp_path / "Bilingual"
    directory.mkdir()
    first = next_bilingual_path(directory, "001_Paper")
    assert first.name == "001_Paper_CN-EN.pdf"
    first.write_bytes(b"v1")
    second = next_bilingual_path(directory, "001_Paper")
    assert second.name == "001_Paper_CN-EN_v2.pdf"
    second.write_bytes(b"v2")
    assert next_bilingual_path(directory, "001_Paper").name == "001_Paper_CN-EN_v3.pdf"


def test_translation_queue_completion_and_retry(tmp_path: Path, monkeypatch) -> None:
    vault = LiteratureVault(1, tmp_path / "Literature")
    assert vault.recover_stale_translation_jobs() == 0
    monkeypatch.setattr(
        "on1y.papers.settings_store.load_paper_settings",
        lambda _user_id: PaperSettings(translation_auto_enqueue=False),
    )
    source = tmp_path / "source.pdf"
    make_pdf(source)
    created = vault.create_batch(
        field="Agents",
        field_code="AG",
        batch_date="2026-09-22",
        records=[{"title": "Queued Paper", "local_pdf_path": str(source)}],
    )
    batch_id = created["batch_id"]
    vault.publish(batch_id)
    monkeypatch.setattr(
        vault,
        "_translation_identity",
        lambda: ("on1y_ai", "qwen-flash", "en", "zh-CN"),
    )

    queued = vault.enqueue_translations(batch_id)
    assert queued["queued_now"] == 1
    assert queued["summary"]["queued"] == 1
    job = vault.claim_next_translation_job()
    assert job is not None
    assert job["status"] == "running"
    assert job["attempt"] == 1

    original = vault.root / job["input_relpath"]
    note = next((original.parent.parent / "Notes").glob("*.md"))
    note.write_text(
        note.read_text("utf-8").rstrip() + "\n\nMy own thought.\n",
        "utf-8",
    )
    first = next_bilingual_path(original.parent.parent / "Bilingual", original.stem)
    make_pdf(first)
    vault.complete_translation_job(
        job["id"],
        first,
        {"input_tokens": 120, "output_tokens": 80, "total_tokens": 200},
    )
    ready = vault.translation_status(batch_id)
    assert ready["summary"]["state"] == "ready"
    assert ready["summary"]["total_tokens"] == 200
    note_text = note.read_text("utf-8")
    assert f"../Bilingual/{first.name}" in note_text
    assert "My own thought." in note_text

    requeued = vault.enqueue_translations(batch_id, force=True)
    assert requeued["queued_now"] == 1
    second_job = vault.claim_next_translation_job()
    assert second_job is not None
    second = next_bilingual_path(original.parent.parent / "Bilingual", original.stem)
    assert second.name.endswith("_v2.pdf")
    make_pdf(second)
    vault.fail_translation_job(second_job["id"], "temporary failure")
    failed = vault.translation_status(batch_id)
    assert failed["summary"]["failed"] == 1
    assert failed["summary"]["state"] == "ready_with_warnings"
    retried = vault.retry_translation_job(second_job["id"])
    assert retried["summary"]["queued"] == 1
    assert first.is_file()


def test_translation_secret_is_masked_and_not_in_babeldoc_command(tmp_path: Path) -> None:
    settings = PaperSettings(translation_api_key="secret-deepl-key")
    public = paper_settings_public_view(settings)
    assert public["translation_api_key"] is None
    assert public["translation_api_key_set"] is True
    assert "secret-deepl-key" not in str(public)

    config = {
        "provider": "deepl",
        "api_key": "secret-deepl-key",
        "deepl_plan": "free",
        "source": "en",
        "target": "zh-CN",
        "model": "DeepL",
    }
    adapter = BabelDocSubprocessAdapter(executable="babeldoc", provider_config=config)
    with LocalTranslationGateway(config) as gateway:
        command = adapter._command(
            input_path=tmp_path / "paper.pdf",
            output_dir=tmp_path,
            source="en",
            target="zh-CN",
            gateway=gateway,
        )
    assert "secret-deepl-key" not in command
    assert "--disable-rich-text-translate" in command
    assert "--disable-graphic-element-process" not in command
    assert "--translate-table-text" not in command
    assert (
        LocalTranslationGateway._extract_translation_text(
            {
                "messages": [
                    {"role": "user", "content": "Now translate the following text:\n\nHello"}
                ]
            }
        )
        == "Hello"
    )


def test_translation_visual_regions_are_flattened_without_touching_caption(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    protected = tmp_path / "protected.pdf"
    document = pymupdf.open()
    page = document.new_page(width=320, height=360)
    page.insert_text((24, 35), "BODY TEXT")
    page.draw_rect(pymupdf.Rect(45, 75, 275, 225), color=(0.2, 0.3, 0.5), fill=(0.9, 0.9, 0.95))
    page.draw_rect(pymupdf.Rect(80, 130, 125, 210), color=(0.2, 0.4, 0.7), fill=(0.2, 0.4, 0.7))
    page.insert_text((90, 105), "CHART LABEL")
    page.insert_text((45, 250), "Figure 1. Caption remains translatable.")
    document.save(source)
    document.close()

    count = flatten_pdf_visual_regions(
        source,
        protected,
        {0: [(40.0, 70.0, 280.0, 230.0)]},
    )
    assert count == 1
    result = pymupdf.open(protected)
    try:
        text = result[0].get_text("text")
        assert "BODY TEXT" in text
        assert "Figure 1. Caption remains translatable." in text
        assert "CHART LABEL" not in text
        assert result[0].get_images(full=True)
    finally:
        result.close()


def test_deepl_gateway_records_billed_characters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status_code = 200
        is_error = False
        headers: dict[str, str] = {}

        @staticmethod
        def json() -> dict[str, object]:
            return {"translations": [{"text": "你好", "billed_characters": 5}]}

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        @staticmethod
        def post(url, *, headers, json):
            captured.update({"url": url, "headers": headers, "json": json})
            return Response()

    monkeypatch.setattr("on1y.papers.translation.httpx.Client", Client)
    gateway = LocalTranslationGateway(
        {
            "provider": "deepl",
            "api_key": "test-key",
            "deepl_plan": "free",
            "source": "en",
            "target": "zh-CN",
        }
    )
    result = gateway.complete({"messages": [{"role": "user", "content": "Input:\n\nHello"}]})
    assert result["choices"][0]["message"]["content"] == "你好"
    assert gateway.usage.character_count == 5
    assert captured["url"] == "https://api-free.deepl.com/v2/translate"
    assert captured["json"]["show_billed_characters"] is True
