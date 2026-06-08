"""Cold-start status must not leak across accounts."""

from __future__ import annotations

from on1y.auth.context import user_context
from on1y.sync.full_sync import _mask_foreign_sync_status, full_sync_status


def test_mask_foreign_sync_status_hides_other_user_progress() -> None:
    foreign = {
        "running": True,
        "user_id": 2,
        "progress": {"events": [{"title": "admin2 video"}]},
        "last_report": {"user_id": 2},
        "error": None,
    }
    with user_context(1):
        masked = _mask_foreign_sync_status(foreign, viewer_user_id=1)
    assert masked["running"] is False
    assert masked["progress"] is None
    assert masked["last_report"] is None


def test_mask_foreign_sync_status_keeps_own_job() -> None:
    own = {
        "running": True,
        "user_id": 1,
        "progress": {"events": [{"title": "mine"}]},
    }
    with user_context(1):
        masked = _mask_foreign_sync_status(own, viewer_user_id=1)
    assert masked["running"] is True
    assert masked["progress"]["events"][0]["title"] == "mine"


def test_full_sync_status_respects_viewer(monkeypatch) -> None:
    import on1y.sync.full_sync as mod

    monkeypatch.setattr(
        mod,
        "_state",
        {
            "running": False,
            "user_id": 2,
            "started_at": None,
            "finished_at": None,
            "last_report": {"hello": "admin2"},
            "last_timing": None,
            "current_phase": "done",
            "phases_ms": {},
            "progress": {"user_id": 2, "events": []},
            "error": None,
        },
        raising=False,
    )
    with user_context(1):
        st = full_sync_status()
    assert st.get("last_report") is None
    assert st.get("progress") is None
