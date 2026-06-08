"""Cold start overlaps poll phases with the parallel ingest pipeline."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from on1y.sync.full_sync import _execute_full_sync


@patch("on1y.sync.full_sync._start_background_distill_after_cold_start")
@patch("on1y.sync.timing.append_timing_record")
@patch("on1y.user.profile.patch_user_profile")
@patch("on1y.sync.full_sync._sync_subscriptions_phase")
@patch("on1y.sync.full_sync._sync_collections_phase")
@patch("on1y.sync.parallel_pipeline.run_parallel_pipeline")
@patch("on1y.subscriptions.sync_job.user_has_pipeline_backlog", return_value=False)
@patch("on1y.user.feeds_config.ensure_user_feeds_config")
@patch("on1y.sync.full_sync.resolve_settings")
@patch("on1y.adapters.sqlite_storage.get_storage")
@patch("on1y.subscriptions.sync_job.subscription_sync_status", return_value={"running": False})
def test_cold_start_runs_pipeline_while_polling(
    _sub_status,
    mock_get_storage,
    mock_resolve_settings,
    _ensure_feeds,
    _has_backlog,
    mock_parallel,
    mock_collections,
    mock_subscriptions,
    _patch_profile,
    _append_timing,
    _bg_distill,
) -> None:
    storage = MagicMock()
    mock_get_storage.return_value = storage
    settings = MagicMock()
    settings.cold_start_bilibili_dynamic_days = 3
    settings.collections_sync_platforms = "bilibili,youtube,zhihu"
    settings.auto_sync_pipeline_batch_size = 25
    mock_resolve_settings.return_value = settings

    mock_collections.return_value = {"enqueued_total": 2}
    mock_subscriptions.return_value = {"bilibili": {}}

    pipeline_started = threading.Event()
    poll_finished = threading.Event()

    def _slow_parallel(*_args, **kwargs) -> dict:
        pipeline_started.set()
        poll_active = kwargs.get("poll_active")
        assert poll_active is not None
        assert poll_active.is_set()
        poll_finished.wait(timeout=5)
        assert not poll_active.is_set()
        return {"mode": "parallel", "distill": {"enabled": True, "distilled": 1}}

    mock_parallel.side_effect = _slow_parallel

    def _collections(*_args, **_kwargs) -> dict:
        assert pipeline_started.wait(timeout=5), "pipeline should start before collections"
        return {"enqueued_total": 2}

    mock_collections.side_effect = _collections

    def _subscriptions(*_args, **_kwargs) -> dict:
        assert pipeline_started.is_set()
        poll_finished.set()
        return {"bilibili": {}}

    mock_subscriptions.side_effect = _subscriptions

    report, error = _execute_full_sync(user_id=1)

    assert error is None
    assert report is not None
    assert report["pipeline"]["mode"] == "parallel"
    mock_parallel.assert_called_once()
    mock_collections.assert_called_once()
    mock_subscriptions.assert_called_once()
