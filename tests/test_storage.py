"""SQLite storage tests."""

from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.queue import QueueEnqueue
from on1y.models.raw import RawItemCreate


def test_enqueue_and_claim(storage) -> None:
    storage.enqueue(QueueEnqueue(url="https://example.com/a", source=SourceType.MANUAL))
    pending = storage.claim_next_pending()
    assert pending is not None
    assert pending.url == "https://example.com/a"
    assert pending.status.value == "processing"
    storage.mark_pending_done(pending.id)


def test_upsert_raw_item(storage) -> None:
    item = RawItemCreate(
        url="https://example.com/doc",
        platform="generic",
        source=SourceType.MANUAL,
        raw_title="Test",
        body_text="Hello world content here.",
        content_type=ContentType.ARTICLE,
        extract_status=ExtractStatus.OK,
    )
    raw = storage.upsert_raw_item(item)
    assert raw.id >= 1
    fetched = storage.get_raw_by_url("https://example.com/doc")
    assert fetched is not None
    assert fetched.word_count == 4


def test_enqueue_helper(storage) -> None:
    pending_id = enqueue_url(storage, "https://example.com/queued", source=SourceType.RSS)
    assert pending_id >= 1
