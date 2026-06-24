from __future__ import annotations

from pathlib import Path

from on1y.auth.context import user_context
from on1y.ingestion.obsidian_import import (
    _parse_note,
    _parse_tags,
    _split_frontmatter,
    import_obsidian_batch,
)
from on1y.obsidian.settings import save_settings


def test_split_frontmatter_and_tags() -> None:
    text = (
        "---\n"
        "title: A Note\n"
        "url: https://example.com/p/1\n"
        "tags: [\"ai\", \"notes\"]\n"
        "---\n"
        "# A Note\n\nBody"
    )
    fm, body = _split_frontmatter(text)
    assert fm["title"] == "A Note"
    assert fm["url"] == "https://example.com/p/1"
    assert _parse_tags(fm["tags"]) == ["ai", "notes"]
    assert "Body" in body


def test_parse_note_without_url_uses_obsidian_scheme(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    inbox = vault / "Inbox" / "Clippings"
    inbox.mkdir(parents=True)
    note = inbox / "sample.md"
    note.write_text("# Sample\n\nOnly markdown body.", encoding="utf-8")

    parsed = _parse_note(note, root_dir=vault)
    assert parsed is not None
    assert parsed.url is not None
    assert parsed.url.startswith("on1y://obsidian/")
    assert parsed.title == "Sample"


def test_import_scans_full_vault_not_only_inbox(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    vault = tmp_path / "vault"
    inbox = vault / "Inbox" / "Clippings"
    inbox.mkdir(parents=True)
    note_outside_inbox = vault / "MyNotes" / "daily.md"
    note_outside_inbox.parent.mkdir(parents=True, exist_ok=True)
    note_outside_inbox.write_text("# Daily\n\noutside inbox note", encoding="utf-8")

    with user_context(1):
        save_settings(
            enabled=True,
            vault_path=str(vault),
            inbox_relpath="Inbox/Clippings",
            auto_distill=False,
        )
        report = import_obsidian_batch(storage, user_id=1, limit=20, auto_distill=False)

    assert report["imported"] >= 1
    rows = storage.list_raw_items(limit=100)
    assert any(
        str(r.platform) == "obsidian" and "MyNotes/daily.md" in r.source_meta.get("obsidian_path", "")
        for r in rows
    )
