from __future__ import annotations

from pathlib import Path

from on1y.ingestion.obsidian_import import _parse_note, _parse_tags, _split_frontmatter


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
    inbox = tmp_path / "Inbox" / "Clippings"
    inbox.mkdir(parents=True)
    note = inbox / "sample.md"
    note.write_text("# Sample\n\nOnly markdown body.", encoding="utf-8")

    parsed = _parse_note(note, inbox_dir=inbox)
    assert parsed is not None
    assert parsed.url is not None
    assert parsed.url.startswith("on1y://obsidian/")
    assert parsed.title == "Sample"
