"""Unread filter on feed listing."""

from __future__ import annotations

from on1y.knowledge.read_state import utc_now_iso
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate


def test_unread_only_filter_with_theme(storage) -> None:
    read = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/read-item",
            platform="bilibili",
            source=SourceType.MANUAL,
            raw_title="已读",
            body_text="b",
            content_type=ContentType.VIDEO,
            extract_status=ExtractStatus.OK,
            source_meta={"read_at": utc_now_iso()},
        )
    )
    unread = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/unread-item",
            platform="bilibili",
            source=SourceType.MANUAL,
            raw_title="未读",
            body_text="b",
            content_type=ContentType.VIDEO,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    rows = storage.list_knowledge_items(collection="feed", unread_only=True, limit=50)
    ids = {int(r["raw_id"]) for r in rows}
    assert unread.id in ids
    assert read.id not in ids
