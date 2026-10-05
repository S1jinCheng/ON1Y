"""Two-device Literature tree transport and filesystem safety tests."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.device_sync.protocol import record_key
from on1y.folder_sync.engine import FolderSync
from on1y.folder_sync.literature_tree import (
    apply_literature_version,
    scan_literature_tree,
)
from on1y.folder_sync.protocol import Event, canonical_relative_path, portable_relative_path
from on1y.papers.literature import LiteratureVault


def _cache_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE folder_sync_file_cache(
        path TEXT PRIMARY KEY,signature TEXT NOT NULL,data TEXT NOT NULL)"""
    )
    return conn


def _store_cache(conn: sqlite3.Connection, scan) -> None:
    for update in scan.cache_updates:
        conn.execute(
            "INSERT OR REPLACE INTO folder_sync_file_cache VALUES (?,?,?)",
            (update.path, update.signature, json.dumps(update.data)),
        )
    conn.commit()


def test_portable_paths_reject_cross_platform_escapes() -> None:
    assert portable_relative_path("Topic/Évidence.md") == "Topic/Évidence.md"
    assert canonical_relative_path("Topic/Évidence.md") == canonical_relative_path(
        "topic/E\u0301VIDENCE.MD"
    )
    for unsafe in (
        "../secret.pdf",
        "/absolute.pdf",
        "folder\\file.pdf",
        "CON.pdf",
        "trailing. ",
        "bad:name.pdf",
        "a//b.pdf",
    ):
        with pytest.raises(ValueError):
            portable_relative_path(unsafe)


def test_scan_stages_content_and_excludes_machine_state(tmp_path: Path) -> None:
    root = tmp_path / "Literature"
    staging = tmp_path / "staging"
    (root / "Topic").mkdir(parents=True)
    (root / "_templates").mkdir()
    (root / "_system" / "cache").mkdir(parents=True)
    (root / ".obsidian").mkdir()
    (root / "Topic" / "paper.pdf").write_bytes(b"PDF")
    (root / "Topic" / "note.md").write_text("note", encoding="utf-8")
    (root / "_templates" / "paper-note.md").write_text("template", encoding="utf-8")
    (root / "_system" / "config.yaml").write_text("version: 1", encoding="utf-8")
    (root / "_system" / "papers.db").write_bytes(b"sqlite")
    (root / "_system" / "cache" / "figure.png").write_bytes(b"cache")
    (root / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
    conn = _cache_connection()

    scan = scan_literature_tree(conn, root, staging)

    paths = {record["fields"]["file"]["path"] for record in scan.records.values()}
    assert paths == {
        "Topic/paper.pdf",
        "Topic/note.md",
        "_templates/paper-note.md",
        "_system/config.yaml",
    }
    assert scan.stats.files == 4
    assert scan.stats.excluded == 3
    assert scan.stats.staged == 4
    assert len(list(staging.iterdir())) == 4

    _store_cache(conn, scan)
    again = scan_literature_tree(conn, root, staging, previous=scan.records)
    assert again.stats.staged == 0
    assert again.stats.cached == 4


def test_scan_rejects_nfc_equivalent_native_file_names(tmp_path: Path) -> None:
    root = tmp_path / "Literature"
    topic = root / "Topic"
    topic.mkdir(parents=True)
    (topic / "\u00c9vidence.md").write_text("composed", encoding="utf-8")
    (topic / "E\u0301vidence.md").write_text("decomposed", encoding="utf-8")
    if len(tuple(topic.iterdir())) != 2:
        pytest.skip("This filesystem aliases NFC-equivalent native names")

    with pytest.raises(ValueError, match="Mac/Windows.*\u51b2\u7a81"):
        scan_literature_tree(_cache_connection(), root, tmp_path / "staging")


def test_deep_cache_and_backups_directories_are_user_content(tmp_path: Path) -> None:
    root = tmp_path / "Literature"
    cache_file = root / "Research" / "cache" / "figures" / "figure.png"
    backup_file = root / "Research" / "backups" / "drafts" / "paper.md"
    cache_file.parent.mkdir(parents=True)
    backup_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"figure")
    backup_file.write_text("draft", encoding="utf-8")

    scan = scan_literature_tree(
        _cache_connection(), root, tmp_path / "staging"
    )

    paths = {record["fields"]["file"]["path"] for record in scan.records.values()}
    assert paths == {
        "Research/cache/figures/figure.png",
        "Research/backups/drafts/paper.md",
    }
    assert scan.stats.files == 2
    assert scan.stats.excluded == 0


def _create_directory_link(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise
    completed = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode:
        pytest.skip(f"Cannot create a test directory link: {completed.stderr}")


def _remove_directory_link(link: Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        os.rmdir(link)


def test_system_link_cannot_redirect_sync_trash_outside_vault(tmp_path: Path) -> None:
    root = tmp_path / "Literature"
    staging = tmp_path / "staging"
    target = root / "Topic" / "note.md"
    target.parent.mkdir(parents=True)
    target.write_text("local work", encoding="utf-8")
    scan = scan_literature_tree(_cache_connection(), root, staging)
    record = next(iter(scan.records.values()))
    active = record["fields"]["file"]
    deleted = {**active, "deleted": True}
    expected = scan.observations[record["identity"]]

    outside = tmp_path / "outside"
    outside.mkdir()
    system_link = root / "_system"
    _create_directory_link(system_link, outside)
    try:
        try:
            result = apply_literature_version(root, deleted, None, expected)
        except ValueError:
            result = None

        assert result is None or not result.applied
        assert target.read_text(encoding="utf-8") == "local work"
        assert not any(outside.rglob("*"))
    finally:
        _remove_directory_link(system_link)


@pytest.mark.parametrize("race", ("created", "modified"))
def test_apply_cas_rechecks_after_staged_copy(
    tmp_path: Path, monkeypatch, race: str
) -> None:
    from on1y.folder_sync import literature_tree

    root = tmp_path / "Literature"
    root.mkdir()
    target = root / "Topic" / "paper.pdf"
    source = tmp_path / "object"
    remote_bytes = b"remote version"
    source.write_bytes(remote_bytes)
    blob = {
        "sha256": hashlib.sha256(remote_bytes).hexdigest(),
        "size": len(remote_bytes),
    }
    version = {"path": "Topic/paper.pdf", "blob": blob, "deleted": False}
    expected = None
    if race == "modified":
        target.parent.mkdir(parents=True)
        target.write_bytes(b"observed version")
        scan = scan_literature_tree(
            _cache_connection(), root, tmp_path / "staging"
        )
        expected = scan.observations[canonical_relative_path("Topic/paper.pdf")]

    staged_copy = literature_tree._stage_verified_copy

    def race_after_copy(copy_source: Path, copy_target: Path, ref):
        temporary = staged_copy(copy_source, copy_target, ref)
        copy_target.parent.mkdir(parents=True, exist_ok=True)
        copy_target.write_bytes(f"concurrent {race}".encode())
        return temporary

    monkeypatch.setattr(literature_tree, "_stage_verified_copy", race_after_copy)

    result = apply_literature_version(root, version, source, expected)

    assert not result.applied
    assert result.reason == "changed"
    assert target.read_bytes() == f"concurrent {race}".encode()
    assert not list(target.parent.glob(".*.tmp"))


def test_apply_uses_cas_and_moves_deletions_to_local_trash(tmp_path: Path) -> None:
    root = tmp_path / "Literature"
    staging = tmp_path / "staging"
    (root / "Topic").mkdir(parents=True)
    target = root / "Topic" / "note.md"
    target.write_text("first", encoding="utf-8")
    conn = _cache_connection()
    scan = scan_literature_tree(conn, root, staging)
    record = next(iter(scan.records.values()))
    identity = record["identity"]
    active = record["fields"]["file"]
    deleted = {**active, "deleted": True}

    target.write_text("changed after scan", encoding="utf-8")
    changed = apply_literature_version(
        root, deleted, None, scan.observations[identity]
    )
    assert not changed.applied and changed.reason == "changed"
    assert target.read_text(encoding="utf-8") == "changed after scan"

    current = scan_literature_tree(conn, root, staging, previous=scan.records)
    result = apply_literature_version(
        root, deleted, None, current.observations[identity]
    )
    assert result.applied and not target.exists()
    trashed = list((root / "_system" / "folder-sync-trash").rglob("note.md"))
    assert len(trashed) == 1
    assert trashed[0].read_text(encoding="utf-8") == "changed after scan"


@pytest.fixture
def tree_pair(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path / "settings"))
    monkeypatch.setenv("ON1Y_BOOTSTRAP_PASSWORD", "test-only-password")
    from on1y.config import get_settings

    get_settings.cache_clear()
    stores = []
    syncs = []
    vaults = []
    for name in ("windows", "mac"):
        data = tmp_path / name
        data.mkdir()
        vault = tmp_path / f"{name}-literature"
        vault.mkdir()
        store = SqliteStorage(data / "on1y.db")
        store.initialize()
        stores.append(store)
        syncs.append(FolderSync(store))
        vaults.append(vault)
    cloud = tmp_path / "cloud"
    syncs[0].configure(1, str(cloud), True, create=True)
    syncs[1].configure(1, str(cloud), True)
    for sync, vault in zip(syncs, vaults, strict=True):
        with sync.conn:
            sync.conn.execute(
                """UPDATE folder_sync_config SET literature_files_enabled=1,
                literature_vault_path=?,literature_initialized=0 WHERE id=1""",
                (str(vault),),
            )
        sync._literature_root = (  # type: ignore[method-assign]
            lambda _user_id, _config=None, selected=vault: selected
        )
    yield syncs[0], syncs[1], vaults[0], vaults[1], cloud
    for store in stores:
        store.close()
    get_settings.cache_clear()


def _cycle(first: FolderSync, second: FolderSync) -> None:
    for sync in (first, second, first, second):
        sync.sync(1)


def _event_documents(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.json")
    ]


def _tree_event_documents(cloud: Path) -> list[dict]:
    return [
        event
        for directory in (cloud / "events", cloud / "literature-events")
        for event in _event_documents(directory)
        if event["kind"] == "literature_file"
    ]


def test_tree_events_use_separate_channel_and_legacy_location_is_read(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    (source / "Topic").mkdir()
    (source / "Topic" / "paper.pdf").write_bytes(b"paper")

    windows.sync(1)

    normal_events = _event_documents(cloud / "events")
    tree_paths = list((cloud / "literature-events").glob("*.json"))
    assert all(event["kind"] != "literature_file" for event in normal_events)
    assert len(tree_paths) == 1
    assert json.loads(tree_paths[0].read_text(encoding="utf-8"))["kind"] == "literature_file"

    # A short-lived development build wrote tree events into the legacy events
    # directory. New clients keep reading that location so those events are not lost.
    misplaced = cloud / "events" / tree_paths[0].name
    tree_paths[0].replace(misplaced)

    mac.sync(1)

    assert (destination / "Topic" / "paper.pdf").read_bytes() == b"paper"


def test_duplicate_event_id_across_channels_with_different_content_stops_sync(
    tree_pair,
) -> None:
    windows, mac, source, _, cloud = tree_pair
    (source / "Topic").mkdir()
    (source / "Topic" / "paper.pdf").write_bytes(b"paper")
    windows.sync(1)
    original_path = next((cloud / "literature-events").glob("*.json"))
    changed = json.loads(original_path.read_text(encoding="utf-8"))
    changed["clock"] += 1
    (cloud / "events" / original_path.name).write_text(
        json.dumps(changed), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="同一同步记录"):
        mac.sync(1)


def test_initialized_vault_receive_first_does_not_publish_defaults_or_conflict(
    tree_pair,
) -> None:
    windows, mac, source, destination, cloud = tree_pair
    LiteratureVault(1, destination).initialize()
    (source / "_templates").mkdir()
    (source / "_system").mkdir()
    (source / "Topic").mkdir()
    (source / "_templates" / "paper-note.md").write_text(
        "remote template", encoding="utf-8"
    )
    (source / "_system" / "config.yaml").write_text(
        "version: 1\ndaily_target: 23\nsource: local-vault\n", encoding="utf-8"
    )
    (source / "Topic" / "paper.pdf").write_bytes(b"paper")

    windows.sync(1)
    published = _tree_event_documents(cloud)
    assert len(published) == 3

    status = mac.sync(1)

    assert (destination / "_templates" / "paper-note.md").read_text(
        encoding="utf-8"
    ) == "remote template"
    assert (destination / "_system" / "config.yaml").read_text(
        encoding="utf-8"
    ) == "version: 1\ndaily_target: 23\nsource: local-vault\n"
    assert (destination / "Topic" / "paper.pdf").read_bytes() == b"paper"
    assert not [item for item in status["conflicts"] if item["field"] == "file"]
    assert len(_tree_event_documents(cloud)) == len(published)
    assert all(
        event["device_id"] != mac.config()["device_id"]
        for event in _tree_event_documents(cloud)
    )
    assert mac.config()["literature_initialized"] == 1


def test_new_library_creator_seeds_generated_defaults(tree_pair) -> None:
    windows, _, source, _, cloud = tree_pair
    LiteratureVault(1, source).initialize()

    windows.sync(1)

    own_events = [
        event
        for event in _tree_event_documents(cloud)
        if event["device_id"] == windows.config()["device_id"]
    ]
    assert {event["patch"]["file"]["path"] for event in own_events} == {
        "_templates/paper-note.md",
        "_system/config.yaml",
    }
    assert windows.config()["literature_initialized"] == 1


def test_joiner_waits_for_creator_seed_barrier_before_initializing(tree_pair) -> None:
    _, mac, _, destination, cloud = tree_pair
    LiteratureVault(1, destination).initialize()

    mac.sync(1)

    assert mac.config()["literature_initialized"] == 0
    assert not _tree_event_documents(cloud)


def test_pristine_join_protects_an_edit_made_after_capture(
    tree_pair, monkeypatch
) -> None:
    windows, mac, source, destination, _ = tree_pair
    LiteratureVault(1, destination).initialize()
    (source / "_templates").mkdir()
    (source / "_templates" / "paper-note.md").write_text(
        "remote template", encoding="utf-8"
    )
    windows.sync(1)

    original_scan = mac._scan_tree
    scans = 0

    def scan_with_concurrent_edit(*args, **kwargs):
        nonlocal scans
        scans += 1
        if scans == 2:
            (destination / "_templates" / "paper-note.md").write_text(
                "local edit during sync", encoding="utf-8"
            )
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(mac, "_scan_tree", scan_with_concurrent_edit)

    mac.sync(1)

    assert (destination / "_templates" / "paper-note.md").read_text(
        encoding="utf-8"
    ) == "local edit during sync"


def test_edit_after_remote_apply_is_published_on_next_cycle(
    tree_pair, monkeypatch
) -> None:
    windows, mac, source, destination, cloud = tree_pair
    LiteratureVault(1, destination).initialize()
    (source / "_templates").mkdir()
    (source / "_templates" / "paper-note.md").write_text(
        "remote template", encoding="utf-8"
    )
    windows.sync(1)

    original_scan = mac._scan_tree
    scans = 0

    def scan_with_post_apply_edit(*args, **kwargs):
        nonlocal scans
        scans += 1
        if scans == 3:
            (destination / "_templates" / "paper-note.md").write_text(
                "local edit after apply", encoding="utf-8"
            )
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(mac, "_scan_tree", scan_with_post_apply_edit)
    mac.sync(1)
    assert not [
        event
        for event in _tree_event_documents(cloud)
        if event["device_id"] == mac.config()["device_id"]
    ]

    mac.sync(1)

    own = [
        event
        for event in _tree_event_documents(cloud)
        if event["device_id"] == mac.config()["device_id"]
        and event["patch"]["file"]["path"] == "_templates/paper-note.md"
    ]
    assert len(own) == 1
    assert own[0]["patch"]["file"]["path"] == "_templates/paper-note.md"
    assert (destination / "_templates" / "paper-note.md").read_text(
        encoding="utf-8"
    ) == "local edit after apply"


def test_pristine_join_waits_for_dot_prefixed_icloud_event_placeholders(
    tree_pair,
) -> None:
    windows, mac, source, destination, cloud = tree_pair
    LiteratureVault(1, destination).initialize()
    original_template = (destination / "_templates" / "paper-note.md").read_bytes()
    (source / "Topic").mkdir()
    (source / "Topic" / "paper.pdf").write_bytes(b"paper")
    windows.sync(1)
    for event_path in (cloud / "literature-events").glob("*.json"):
        event_path.rename(event_path.with_name("." + event_path.name + ".icloud"))

    mac.sync(1)

    assert (destination / "_templates" / "paper-note.md").read_bytes() == original_template
    assert not (destination / "Topic" / "paper.pdf").exists()
    assert mac.config()["literature_initialized"] == 0


def test_pristine_join_waits_for_all_remote_objects_before_applying(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    LiteratureVault(1, destination).initialize()
    default_template = (destination / "_templates" / "paper-note.md").read_bytes()
    default_config = (destination / "_system" / "config.yaml").read_bytes()
    (source / "_templates").mkdir()
    (source / "Topic").mkdir()
    (source / "_templates" / "paper-note.md").write_text(
        "remote template", encoding="utf-8"
    )
    (source / "Topic" / "paper.pdf").write_bytes(b"remote paper")

    windows.sync(1)
    events = _tree_event_documents(cloud)
    missing_event = next(
        event
        for event in events
        if event["patch"]["file"]["path"] == "Topic/paper.pdf"
    )
    sha256 = missing_event["patch"]["file"]["blob"]["sha256"]
    (cloud / "objects" / sha256).replace(cloud.parent / f"held-{sha256}")

    mac.sync(1)

    assert (destination / "_templates" / "paper-note.md").read_bytes() == default_template
    assert (destination / "_system" / "config.yaml").read_bytes() == default_config
    assert not (destination / "Topic" / "paper.pdf").exists()
    assert mac.config()["literature_initialized"] == 0
    assert all(
        event["device_id"] != mac.config()["device_id"]
        for event in _tree_event_documents(cloud)
    )


def test_pristine_join_waits_for_every_seed_event_before_applying(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    LiteratureVault(1, destination).initialize()
    default_template = (destination / "_templates" / "paper-note.md").read_bytes()
    (source / "_templates").mkdir()
    (source / "Topic").mkdir()
    (source / "_templates" / "paper-note.md").write_text(
        "remote template", encoding="utf-8"
    )
    (source / "Topic" / "paper.pdf").write_bytes(b"remote paper")
    windows.sync(1)
    held = next(
        path
        for path in (cloud / "literature-events").glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["patch"]["file"]["path"]
        == "Topic/paper.pdf"
    )
    held.replace(cloud.parent / held.name)

    mac.sync(1)

    assert (destination / "_templates" / "paper-note.md").read_bytes() == default_template
    assert not (destination / "Topic" / "paper.pdf").exists()
    assert mac.config()["literature_initialized"] == 0


def test_pristine_join_rebuilds_portable_literature_catalog(tree_pair) -> None:
    windows, mac, source, destination, _ = tree_pair
    source_vault = LiteratureVault(1, source)
    input_pdf = source.parent / "catalog-input.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Portable catalog integration")
    document.save(input_pdf)
    document.close()
    created = source_vault.create_batch(
        field="Human-AI Interaction",
        field_code="HAI",
        batch_date="2026-10-05",
        records=[
            {
                "title": "Portable Catalog",
                "authors": ["A. Author"],
                "year": 2026,
                "venue": "CHI",
                "doi": "10.1000/portable-engine",
                "local_pdf_path": str(input_pdf),
                "area": "Human-AI Interaction",
                "recommendation": "Read",
            }
        ],
    )
    batch_id = str(created["batch_id"])
    published = source_vault.publish(batch_id)
    paper_id = str(published["papers"][0]["id"])
    LiteratureVault(1, destination).initialize()

    windows.sync(1)
    mac.sync(1)

    rebuilt = LiteratureVault(1, destination).batch(batch_id)
    assert rebuilt is not None
    assert rebuilt["papers"][0]["id"] == paper_id
    assert rebuilt["papers"][0]["position"] == 1
    role_paths = []
    for field in ("original_pdf_relpath", "note_relpath"):
        relative = rebuilt["papers"][0][field]
        role_paths.append(relative)
        assert (destination / relative).is_file()
    with LiteratureVault(1, destination).connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    with source_vault.connect() as conn:
        conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
        conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
        conn.commit()
    for relative in role_paths:
        (source / relative).unlink()

    windows.sync(1)
    mac.sync(1)

    assert LiteratureVault(1, destination).batch(batch_id) is None
    with LiteratureVault(1, destination).connect() as conn:
        assert conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is None
    assert all(not (destination / relative).exists() for relative in role_paths)


def test_tree_roundtrip_exclusions_and_recoverable_delete(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    (source / "Topic").mkdir()
    (source / "_templates").mkdir()
    (source / "_system" / "cache").mkdir(parents=True)
    (source / ".obsidian").mkdir()
    (source / "Topic" / "paper.pdf").write_bytes(b"paper-v1")
    (source / "Topic" / "note.md").write_text("note", encoding="utf-8")
    (source / "_templates" / "note.md").write_text("template", encoding="utf-8")
    with sqlite3.connect(source / "_system" / "papers.db") as catalog:
        catalog.execute("CREATE TABLE local_only(value TEXT)")
    (source / "_system" / "cache" / "figure.png").write_bytes(b"never")
    (source / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")

    _cycle(windows, mac)

    assert (destination / "Topic" / "paper.pdf").read_bytes() == b"paper-v1"
    assert (destination / "Topic" / "note.md").read_text(encoding="utf-8") == "note"
    assert (destination / "_templates" / "note.md").is_file()
    assert not (destination / "_system" / "papers.db").exists()
    assert not (destination / ".obsidian").exists()
    tree_events = _tree_event_documents(cloud)
    assert len(tree_events) == 3
    assert all(str(source) not in json.dumps(event) for event in tree_events)

    (source / "Topic" / "note.md").unlink()
    _cycle(windows, mac)
    assert not (destination / "Topic" / "note.md").exists()
    assert list((destination / "_system" / "folder-sync-trash").rglob("note.md"))
    deleted_key = record_key("literature_file", canonical_relative_path("Topic/note.md"))
    mac.restore(1, deleted_key)
    _cycle(mac, windows)
    assert (source / "Topic" / "note.md").read_text(encoding="utf-8") == "note"


def test_concurrent_tree_edits_keep_both_objects_until_resolution(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    (source / "Topic").mkdir()
    source_file = source / "Topic" / "paper.pdf"
    source_file.write_bytes(b"seed")
    _cycle(windows, mac)
    destination_file = destination / "Topic" / "paper.pdf"

    source_file.write_bytes(b"windows edit")
    destination_file.write_bytes(b"mac edit")
    windows.capture(1)
    mac.capture(1)
    _cycle(windows, mac)

    conflict = next(
        item
        for item in windows.status(1)["conflicts"]
        if item["field"] == "file" and item["title"] == "Topic/paper.pdf"
    )
    assert source_file.read_bytes() == b"windows edit"
    assert destination_file.read_bytes() == b"mac edit"
    hashes = {version["value"]["blob"]["sha256"] for version in conflict["versions"]}
    assert hashes <= {path.name for path in (cloud / "objects").iterdir()}

    chosen = next(
        version
        for version in conflict["versions"]
        if version["value"]["blob"]["sha256"]
        == next(
            json.loads(row[0])["sha256"]
            for row in mac.conn.execute(
                "SELECT data FROM folder_sync_file_cache WHERE path=?",
                (str(destination_file),),
            )
        )
    )
    windows.resolve(1, conflict["key"], "file", chosen["id"])
    _cycle(windows, mac)
    assert source_file.read_bytes() == destination_file.read_bytes() == b"mac edit"


def test_concurrent_delete_and_edit_do_not_overwrite_each_other(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    (source / "Topic").mkdir()
    source_file = source / "Topic" / "paper.md"
    source_file.write_text("seed", encoding="utf-8")
    _cycle(windows, mac)
    destination_file = destination / "Topic" / "paper.md"

    source_file.unlink()
    destination_file.write_text("edited on mac", encoding="utf-8")
    windows.capture(1)
    mac.capture(1)
    _cycle(windows, mac)

    conflict = next(
        item
        for item in windows.status(1)["conflicts"]
        if item["field"] == "file" and item["title"] == "Topic/paper.md"
    )
    versions = [version["value"] for version in conflict["versions"]]
    assert {version["deleted"] for version in versions} == {False, True}
    assert not source_file.exists()
    assert destination_file.read_text(encoding="utf-8") == "edited on mac"
    assert {version["blob"]["sha256"] for version in versions} <= {
        path.name for path in (cloud / "objects").iterdir()
    }

    edited = next(
        version for version in conflict["versions"] if not version["value"]["deleted"]
    )
    windows.resolve(1, conflict["key"], "file", edited["id"])
    _cycle(windows, mac)
    assert source_file.read_text(encoding="utf-8") == "edited on mac"
    assert destination_file.read_text(encoding="utf-8") == "edited on mac"


def test_first_sync_into_empty_receiver_does_not_publish_tombstones(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    (source / "Topic").mkdir()
    (source / "Topic" / "paper.pdf").write_bytes(b"paper")

    windows.sync(1)
    assert len(_tree_event_documents(cloud)) == 1
    mac.sync(1)

    tree_events = _tree_event_documents(cloud)
    assert len(tree_events) == 1
    assert tree_events[0]["patch"]["file"]["deleted"] is False
    assert (destination / "Topic" / "paper.pdf").read_bytes() == b"paper"


def test_unavailable_file_retains_previous_version_without_tombstone(
    tmp_path: Path, monkeypatch
) -> None:
    from on1y.folder_sync import literature_tree

    root = tmp_path / "Literature"
    staging = tmp_path / "staging"
    root.mkdir()
    target = root / "paper.pdf"
    target.write_bytes(b"paper")
    conn = _cache_connection()
    initial = scan_literature_tree(conn, root, staging)
    previous = next(iter(initial.records.values()))["fields"]["file"]
    actual_available = literature_tree.available
    monkeypatch.setattr(
        literature_tree,
        "available",
        lambda path: False if Path(path) == target else actual_available(path),
    )

    scan = scan_literature_tree(conn, root, staging, previous=initial.records)

    retained = next(iter(scan.records.values()))["fields"]["file"]
    assert retained == previous
    assert retained["deleted"] is False
    assert scan.stats.unavailable == 1
    assert scan.stats.deleted == 0


def test_rename_reuses_one_immutable_object(tree_pair) -> None:
    windows, mac, source, destination, cloud = tree_pair
    (source / "Topic").mkdir()
    old_source = source / "Topic" / "old.md"
    new_source = source / "Topic" / "new.md"
    old_source.write_text("same bytes", encoding="utf-8")
    _cycle(windows, mac)
    assert len(list((cloud / "objects").iterdir())) == 1

    old_source.rename(new_source)
    _cycle(windows, mac)

    assert len(list((cloud / "objects").iterdir())) == 1
    assert not (destination / "Topic" / "old.md").exists()
    assert (destination / "Topic" / "new.md").read_text(encoding="utf-8") == "same bytes"
    assert list((destination / "_system" / "folder-sync-trash").rglob("old.md"))


@pytest.mark.parametrize(
    ("path", "identity"),
    (
        ("../secret.pdf", "../secret.pdf"),
        ("C:/secret.pdf", "c:/secret.pdf"),
        ("Topic\\secret.pdf", "topic/secret.pdf"),
        ("CON.pdf", "con.pdf"),
        ("Topic/paper.pdf", "different/path.pdf"),
    ),
)
def test_remote_literature_event_rejects_malicious_or_mismatched_paths(
    path: str, identity: str
) -> None:
    with pytest.raises(ValueError):
        Event(
            library_id=uuid4(),
            id=uuid4(),
            device_id=uuid4(),
            clock=1,
            kind="literature_file",
            identity=identity,
            patch={
                "file": {
                    "path": path,
                    "blob": {"sha256": "0" * 64, "size": 1},
                    "deleted": False,
                }
            },
            parents={"file": []},
        )
