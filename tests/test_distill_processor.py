"""Distill processor short-content behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.distill.processor import (
    SHORT_CONTENT_DISTILL_MAX_CHARS,
    distill_raw_item,
    is_short_content_for_distill,
)
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItem


def test_is_short_content_for_distill() -> None:
    assert is_short_content_for_distill("a" * (SHORT_CONTENT_DISTILL_MAX_CHARS - 1))
    assert not is_short_content_for_distill("a" * SHORT_CONTENT_DISTILL_MAX_CHARS)


def test_distill_short_content_skips_llm() -> None:
    body = "这是一条很短的知乎回答或推文。"
    raw = RawItem(
        id=7,
        url="https://x.com/u/status/1",
        platform="twitter",
        source=SourceType.RSS,
        raw_title="short",
        body_text=body,
        content_type=ContentType.ARTICLE,
        extract_status=ExtractStatus.OK,
    )
    storage = MagicMock()
    storage.get_raw_by_id.return_value = raw
    storage.get_distilled_by_raw_id.return_value = None
    storage.get_raw_theme_source.return_value = None
    storage.upsert_distilled.return_value = 99

    with patch("on1y.distill.processor.get_llm_client") as mock_client:
        distilled_id = distill_raw_item(storage, 7)

    assert distilled_id == 99
    mock_client.assert_not_called()
    storage.upsert_distilled.assert_called_once()
    assert storage.upsert_distilled.call_args.kwargs["summary"] == body
    assert storage.upsert_distilled.call_args.kwargs["model"] is None
    storage.merge_extracted_tags.assert_called_once()


def test_distill_long_content_uses_llm() -> None:
    body = "x" * (SHORT_CONTENT_DISTILL_MAX_CHARS + 20)
    raw = RawItem(
        id=8,
        url="https://www.zhihu.com/question/1/answer/2",
        platform="zhihu",
        source=SourceType.RSS,
        raw_title="long",
        body_text=body,
        content_type=ContentType.ARTICLE,
        extract_status=ExtractStatus.OK,
    )
    storage = MagicMock()
    storage.get_raw_by_id.return_value = raw
    storage.get_distilled_by_raw_id.return_value = None
    storage.get_raw_theme_source.return_value = None
    storage.list_active_themes.return_value = [
        {"slug": "other", "name_zh": "其他", "description_zh": ""}
    ]
    storage.upsert_distilled.return_value = 100

    client = MagicMock()
    client.chat_json.return_value = {
        "summary": "要点摘要",
        "theme": "other",
        "tags": ["tag1"],
    }

    with patch("on1y.distill.processor.get_llm_client", return_value=client):
        distill_raw_item(storage, 8)

    client.chat_json.assert_called_once()
