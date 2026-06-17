"""Feed date filter on knowledge items API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from on1y.knowledge.feed_dates import local_today
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.web.app import create_app


def test_knowledge_items_feed_date_filter(storage) -> None:
    today_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    old_iso = "2020-01-15T12:00:00Z"
    storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/feed-today",
            platform="bilibili",
            source=SourceType.MANUAL,
            raw_title="今日条目",
            body_text="b",
            content_type=ContentType.VIDEO,
            extract_status=ExtractStatus.OK,
            source_meta={"published": today_iso},
        )
    )
    storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/feed-old",
            platform="bilibili",
            source=SourceType.MANUAL,
            raw_title="旧条目",
            body_text="b",
            content_type=ContentType.VIDEO,
            extract_status=ExtractStatus.OK,
            source_meta={"published": old_iso},
        )
    )
    client = TestClient(create_app())
    day = local_today().isoformat()
    response = client.get("/api/knowledge/items", params={"feed_date": day, "limit": 50})
    assert response.status_code == 200
    payload = response.json()
    assert payload["feed_date"] == day
    titles = [item["title"] for item in payload["items"]]
    assert "今日条目" in titles
    assert "旧条目" not in titles


def test_resolve_sync_since_ts_caps_backfill() -> None:
    from on1y.subscriptions.settings import resolve_sync_since_ts

    ancient = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    resolved = resolve_sync_since_ts(
        "bilibili",
        sync_since_ts=ancient,
        backfill=True,
        backfill_max_days=7,
    )
    assert resolved is not None
    week_ago = int(datetime.now(timezone.utc).timestamp()) - 7 * 86400
    assert resolved >= week_ago - 60
