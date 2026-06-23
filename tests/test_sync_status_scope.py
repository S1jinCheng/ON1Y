"""Sync status endpoints should hide foreign users."""

from __future__ import annotations

from fastapi.testclient import TestClient

from on1y.web.app import create_app


def test_subscription_sync_status_masks_foreign_owner(monkeypatch) -> None:
    import on1y.subscriptions.sync_job as sync_job

    monkeypatch.setattr(
        sync_job,
        "subscription_sync_status",
        lambda: {
            "running": True,
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": None,
            "last_report": {"user_id": 2},
            "error": "x",
            "user_id": 2,
            "mode": "auto",
            "backfill": True,
            "progress": {"events": [{"title": "foreign"}]},
        },
    )
    client = TestClient(create_app())
    resp = client.get("/api/subscriptions/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["user_id"] is None
    assert data["last_report"] is None
    assert data["progress"] is None
    assert data["mode"] is None


def test_collections_sync_status_masks_foreign_owner(monkeypatch) -> None:
    import on1y.subscriptions.collections_auto_sync as collections

    monkeypatch.setattr(
        collections,
        "collections_sync_status",
        lambda: {
            "running": True,
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": None,
            "user_id": 2,
            "last_report": {"enqueued_total": 10},
            "last_error": "oops",
        },
    )
    client = TestClient(create_app())
    resp = client.get("/api/collections/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["user_id"] is None
    assert data["last_report"] is None
    assert data["last_error"] is None
