"""Cold start pipeline drains ingest without blocking on LLM distill."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.sync.full_sync import _drain_ingest_pipeline


def test_drain_ingest_pipeline_skips_distill() -> None:
    storage = MagicMock()
    storage.count_pending_for_platform.return_value = 0

    with patch("on1y.sync.full_sync._pipeline_ingest_batch") as mock_ingest, patch(
        "on1y.sync.full_sync._pipeline_distill_batch"
    ) as mock_distill:
        _drain_ingest_pipeline(storage, platforms=["bilibili", "youtube", "zhihu"])

    mock_distill.assert_not_called()
    mock_ingest.assert_not_called()
