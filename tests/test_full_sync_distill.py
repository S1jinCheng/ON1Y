"""Cold-start pipeline distill progress uses raw_title."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItem


def test_pipeline_distill_batch_uses_raw_title() -> None:
    from on1y.sync.full_sync import _pipeline_distill_batch

    raw = RawItem(
        id=42,
        url="https://www.bilibili.com/video/BV1test",
        platform="bilibili",
        source=SourceType.RSS,
        raw_title="测试标题",
        body_text="body",
        content_type=ContentType.VIDEO,
        extract_status=ExtractStatus.OK,
    )
    storage = MagicMock()
    storage.get_raw_by_id.return_value = raw
    progress = MagicMock()

    with patch(
        "on1y.distill.processor.list_distill_candidate_ids", return_value=[42]
    ), patch("on1y.distill.processor.distill_raw_item"), patch(
        "on1y.llm.settings.get_resolved_llm_settings"
    ) as mock_llm:
        mock_llm.return_value.api_key_set = True
        _pipeline_distill_batch(
            storage,
            platform="bilibili",
            limit=5,
            progress=progress,
        )

    logged_titles = [c.kwargs.get("title") for c in progress.log_item.call_args_list]
    assert "测试标题" in logged_titles
