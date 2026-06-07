"""Cold start pipeline drains ingest without blocking on LLM distill."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.sync.full_sync import _drain_ingest_pipeline


def test_drain_ingest_pipeline_delegates_to_parallel() -> None:
    storage = MagicMock()

    with patch("on1y.sync.parallel_pipeline.run_parallel_pipeline") as mock_parallel:
        mock_parallel.return_value = {"mode": "parallel", "distill": {"enabled": True}}
        result = _drain_ingest_pipeline(
            storage, platforms=["bilibili", "youtube", "zhihu"], user_id=2
        )

    mock_parallel.assert_called_once()
    assert result["mode"] == "parallel"
