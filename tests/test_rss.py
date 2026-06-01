"""RSS polling logic tests (no network)."""

from on1y.ingestion.rss import _is_newer


def test_is_newer_by_published() -> None:
    assert _is_newer(
        "entry-2",
        "Wed, 01 Jan 2025 12:00:00 GMT",
        "entry-1",
        "Wed, 01 Jan 2024 12:00:00 GMT",
    )


def test_is_newer_same_id() -> None:
    assert not _is_newer("entry-1", None, "entry-1", None)
