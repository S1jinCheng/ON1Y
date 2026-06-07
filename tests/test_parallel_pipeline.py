"""Parallel pipeline queue detection."""

from __future__ import annotations

from unittest.mock import MagicMock

from on1y.sync.parallel_pipeline import _pipeline_has_work


def test_pipeline_has_work_when_pending_ingest() -> None:
    storage = MagicMock()
    storage.count_pending_for_platform.return_value = 2
    storage.count_subtitles_by_status.return_value = {}
    assert _pipeline_has_work(
        storage, platforms=["bilibili"], distill_enabled=True
    )


def test_pipeline_has_work_when_idle() -> None:
    storage = MagicMock()
    storage.count_pending_for_platform.return_value = 0
    storage.count_subtitles_by_status.return_value = {}
    storage.count_raw_ids_needing_distill.return_value = 0
    assert not _pipeline_has_work(
        storage, platforms=["bilibili"], distill_enabled=True
    )
