"""Reads must never return all users when schema v9+ is active."""

from __future__ import annotations

from on1y.auth.context import user_context
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate


def test_list_knowledge_scoped_without_request_user(storage) -> None:
    from on1y.user.accounts import UserStore

    store = UserStore(storage)
    user2 = store.create_user(username="alice2", password="password1234")
    uid2 = user2.id
    with user_context(1):
        storage.upsert_raw_item(
            RawItemCreate(
                url="https://example.com/u1",
                platform="web",
                source=SourceType.MANUAL,
                raw_title="user one",
                body_text="a",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
            )
        )
    with user_context(uid2):
        storage.upsert_raw_item(
            RawItemCreate(
                url="https://example.com/u2",
                platform="web",
                source=SourceType.MANUAL,
                raw_title="user two",
                body_text="b",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
            )
        )

    # No request user in context: must default to user 1, not leak all rows.
    items = storage.list_knowledge_items(limit=50)
    titles = {str(i.get("title") or "") for i in items}
    assert "user one" in titles
    assert "user two" not in titles

    with user_context(uid2):
        items2 = storage.list_knowledge_items(limit=50)
        titles2 = {str(i.get("title") or "") for i in items2}
        assert "user two" in titles2
        assert "user one" not in titles2
