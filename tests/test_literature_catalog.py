"""Portable Literature catalog sidecar tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from on1y.papers.literature import LiteratureVault
from on1y.papers.literature_catalog import (
    CATALOG_ROOT,
    LiteratureCatalogConflictError,
    LiteratureCatalogError,
    export_catalog_sidecars,
    plan_catalog_reconcile,
    reconcile_catalog_sidecars,
)


def _make_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Portable Literature catalog")
    document.save(path)
    document.close()


def _source_catalog(tmp_path: Path, library_id: str) -> tuple[LiteratureVault, str, str]:
    vault = LiteratureVault(1, tmp_path / "source-vault")
    local_pdf = tmp_path / "source.pdf"
    _make_pdf(local_pdf)
    created = vault.create_batch(
        field="Human-AI Interaction",
        field_code="HAI",
        batch_date="2026-10-05",
        records=[
            {
                "title": "Portable Catalog Paper",
                "authors": ["A. Author", "B. Author"],
                "abstract": "Remote abstract",
                "year": 2026,
                "venue": "CHI",
                "doi": "10.1000/portable-catalog",
                "local_pdf_path": str(local_pdf),
                "area": "Human-AI Interaction",
                "recommendation": "Read this portable paper.",
            }
        ],
    )
    assert created["created"] is True
    batch_id = str(created["batch_id"])
    published = vault.publish(batch_id)
    paper_id = str(published["papers"][0]["id"])
    original_relpath = str(published["papers"][0]["original_pdf_relpath"])
    bilingual_relpath = (
        Path("Human-AI-Interaction")
        / "2026-10-05"
        / "Bilingual"
        / "001_Portable_Catalog_Paper.bilingual.pdf"
    ).as_posix()
    bilingual = vault.root / bilingual_relpath
    bilingual.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vault.root / original_relpath, bilingual)
    with vault.connect() as conn:
        conn.execute(
            "UPDATE papers SET bilingual_pdf_relpath=? WHERE id=?",
            (bilingual_relpath, paper_id),
        )
        conn.commit()
    report = export_catalog_sidecars(vault, library_id=library_id)
    assert report["exported"] is True
    assert report["papers"] == report["batches"] == report["memberships"] == 1
    return vault, batch_id, paper_id


def _copy_portable_tree(source: LiteratureVault, destination: LiteratureVault) -> None:
    destination.root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source.root / "_catalog", destination.root / "_catalog")
    shutil.copytree(
        source.root / "Human-AI-Interaction",
        destination.root / "Human-AI-Interaction",
    )


def _single_paper_sidecar(vault: LiteratureVault) -> Path:
    paths = list((vault.root / CATALOG_ROOT / "papers").glob("*.json"))
    assert len(paths) == 1
    return paths[0]


def test_catalog_roundtrip_rebuilds_core_tables_and_roles(tmp_path: Path) -> None:
    library_id = str(uuid4())
    source, batch_id, paper_id = _source_catalog(tmp_path, library_id)
    receiver = LiteratureVault(1, tmp_path / "receiver-vault")
    _copy_portable_tree(source, receiver)

    assert not receiver.db_path.exists()
    plan = plan_catalog_reconcile(receiver, library_id=library_id)
    assert len(plan.papers) == len(plan.batches) == len(plan.memberships) == 1

    report = reconcile_catalog_sidecars(receiver, library_id=library_id)
    assert report == {
        "reconciled": True,
        "dry_run": False,
        "skipped": None,
        "papers_inserted": 1,
        "batches_inserted": 1,
        "memberships_inserted": 1,
        "fields_filled": 0,
        "papers_deleted": 0,
        "batches_deleted": 0,
        "warnings": [],
    }
    rebuilt = receiver.batch(batch_id)
    assert rebuilt is not None
    assert rebuilt["field"] == "Human-AI Interaction"
    assert rebuilt["papers"][0]["id"] == paper_id
    assert rebuilt["papers"][0]["position"] == 1
    assert rebuilt["papers"][0]["authors"] == ["A. Author", "B. Author"]
    assert rebuilt["papers"][0]["original_pdf_relpath"]
    assert rebuilt["papers"][0]["bilingual_pdf_relpath"]
    assert rebuilt["papers"][0]["note_relpath"]
    for name in (
        "original_pdf_relpath",
        "bilingual_pdf_relpath",
        "note_relpath",
    ):
        assert (receiver.root / rebuilt["papers"][0][name]).is_file()
    with receiver.connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    repeated = reconcile_catalog_sidecars(receiver, library_id=library_id)
    assert repeated["papers_inserted"] == 0
    assert repeated["batches_inserted"] == 0
    assert repeated["memberships_inserted"] == 0
    assert repeated["fields_filled"] == 0

    sidecar_text = _single_paper_sidecar(source).read_text(encoding="utf-8")
    assert str(tmp_path) not in sidecar_text
    assert '"source_url": null' in sidecar_text


def test_catalog_export_missing_or_empty_db_is_strict_noop(tmp_path: Path) -> None:
    library_id = str(uuid4())
    vault = LiteratureVault(1, tmp_path / "empty-vault")
    remote = vault.root / CATALOG_ROOT / "papers" / "remote.json"
    remote.parent.mkdir(parents=True)
    remote.write_bytes(b"remote-sidecar-must-survive")
    before = remote.read_bytes()

    missing = export_catalog_sidecars(vault, library_id=library_id)
    assert missing["skipped"] == "db_missing"
    assert remote.read_bytes() == before

    vault.initialize()
    empty = export_catalog_sidecars(vault, library_id=library_id)
    assert empty["skipped"] == "db_empty"
    assert empty["files_written"] == 0
    assert remote.read_bytes() == before
    assert set((vault.root / CATALOG_ROOT).rglob("*")) == {
        vault.root / CATALOG_ROOT / "papers",
        remote,
    }


def test_authoritative_catalog_tombstones_delete_receiver_rows(tmp_path: Path) -> None:
    library_id = str(uuid4())
    source, batch_id, paper_id = _source_catalog(tmp_path, library_id)
    receiver = LiteratureVault(1, tmp_path / "receiver-vault")
    _copy_portable_tree(source, receiver)
    reconcile_catalog_sidecars(receiver, library_id=library_id)
    source_paper = source.batch(batch_id)["papers"][0]
    role_paths = [
        source_paper[name]
        for name in ("original_pdf_relpath", "bilingual_pdf_relpath", "note_relpath")
        if source_paper.get(name)
    ]

    with source.connect() as conn:
        conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
        conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
        conn.commit()
    for relative in role_paths:
        (source.root / relative).unlink()

    exported = export_catalog_sidecars(
        source, library_id=library_id, authoritative=True
    )
    assert exported["tombstones_written"] == 2
    for kind in ("papers", "batches"):
        for sidecar in (source.root / CATALOG_ROOT / kind).glob("*.json"):
            shutil.copy2(sidecar, receiver.root / CATALOG_ROOT / kind / sidecar.name)
    for relative in role_paths:
        (receiver.root / relative).unlink()

    plan = plan_catalog_reconcile(receiver, library_id=library_id)
    assert plan.deleted_paper_ids == (paper_id,)
    assert plan.deleted_batch_ids == (batch_id,)
    report = reconcile_catalog_sidecars(receiver, library_id=library_id)
    assert report["papers_deleted"] == report["batches_deleted"] == 1
    assert receiver.batch(batch_id) is None
    with receiver.connect() as conn:
        assert conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is None


def test_catalog_reconcile_fills_only_empty_local_fields(tmp_path: Path) -> None:
    library_id = str(uuid4())
    source, _batch_id, paper_id = _source_catalog(tmp_path, library_id)
    receiver = LiteratureVault(1, tmp_path / "receiver-vault")
    _copy_portable_tree(source, receiver)
    reconcile_catalog_sidecars(receiver, library_id=library_id)
    with receiver.connect() as conn:
        conn.execute(
            "UPDATE papers SET abstract=NULL,venue='Local Venue',status='read' WHERE id=?",
            (paper_id,),
        )
        conn.commit()

    report = reconcile_catalog_sidecars(receiver, library_id=library_id)
    with receiver.connect() as conn:
        paper = conn.execute(
            "SELECT abstract,venue,status FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
    assert dict(paper) == {
        "abstract": "Remote abstract",
        "venue": "Local Venue",
        "status": "read",
    }
    assert report["fields_filled"] == 1
    assert f"preserved local paper {paper_id} field venue" in report["warnings"]
    assert f"preserved local paper {paper_id} field status" in report["warnings"]


def test_catalog_conflict_rolls_back_fills_atomically(tmp_path: Path) -> None:
    library_id = str(uuid4())
    source, batch_id, paper_id = _source_catalog(tmp_path, library_id)
    receiver = LiteratureVault(1, tmp_path / "receiver-vault")
    _copy_portable_tree(source, receiver)
    reconcile_catalog_sidecars(receiver, library_id=library_id)
    with receiver.connect() as conn:
        conn.execute("UPDATE papers SET abstract=NULL WHERE id=?", (paper_id,))
        conn.execute(
            "UPDATE batch_papers SET position=2 WHERE batch_id=? AND paper_id=?",
            (batch_id, paper_id),
        )
        conn.commit()

    with pytest.raises(LiteratureCatalogConflictError, match="conflicting position"):
        reconcile_catalog_sidecars(receiver, library_id=library_id)

    with receiver.connect() as conn:
        paper = conn.execute("SELECT abstract FROM papers WHERE id=?", (paper_id,)).fetchone()
        membership = conn.execute(
            "SELECT position FROM batch_papers WHERE batch_id=? AND paper_id=?",
            (batch_id, paper_id),
        ).fetchone()
    assert paper["abstract"] is None
    assert membership["position"] == 2


def test_catalog_rejects_unsafe_role_before_creating_database(tmp_path: Path) -> None:
    library_id = str(uuid4())
    source, _batch_id, _paper_id = _source_catalog(tmp_path, library_id)
    receiver = LiteratureVault(1, tmp_path / "receiver-vault")
    _copy_portable_tree(source, receiver)
    sidecar = _single_paper_sidecar(receiver)
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["paper"]["roles"]["note"] = "../outside.md"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiteratureCatalogError, match="roles.note"):
        reconcile_catalog_sidecars(receiver, library_id=library_id)
    assert not receiver.db_path.exists()


def test_catalog_rejects_wrong_library_before_creating_database(tmp_path: Path) -> None:
    library_id = str(uuid4())
    source, _batch_id, _paper_id = _source_catalog(tmp_path, library_id)
    receiver = LiteratureVault(1, tmp_path / "receiver-vault")
    _copy_portable_tree(source, receiver)

    with pytest.raises(LiteratureCatalogConflictError, match="library_id"):
        reconcile_catalog_sidecars(receiver, library_id=str(uuid4()))
    assert not receiver.db_path.exists()
