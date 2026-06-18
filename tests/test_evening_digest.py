"""Evening digest aggregation and API."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from on1y.auth.context import user_context
from on1y.digest.evening import (
    aggregate_evening_stats,
    build_evening_digest,
    evening_digest_status,
    latest_evening_digest_status,
    load_evening_digest,
    mark_evening_digest_read,
    today_digest_date,
)
from on1y.web.app import create_app


def test_aggregate_evening_stats_empty(storage, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    from on1y.config import get_settings

    get_settings.cache_clear()
    try:
        with user_context(1):
            stats = aggregate_evening_stats(storage, day=date.today().isoformat())
        assert stats["published_total"] == 0
        assert stats["unread_total"] == 0
    finally:
        get_settings.cache_clear()


def test_build_evening_digest_without_llm(storage, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    def _no_llm(*_a, **_k):
        return None, "llm_not_configured"

    monkeypatch.setattr("on1y.digest.evening.generate_evening_llm_summary", _no_llm)
    try:
        with user_context(1):
            doc = build_evening_digest(storage, day="2026-06-01", force=True)
        assert doc["digest_date"] == "2026-06-01"
        assert doc["llm_error"] == "llm_not_configured"
        assert load_evening_digest(1, "2026-06-01") is not None
        marked = mark_evening_digest_read(1, "2026-06-01")
        assert marked is not None
        assert marked.get("read_at")
        status = latest_evening_digest_status(1)
        assert status["today_available"] is False
        assert status["today_unread"] is False
    finally:
        get_settings.cache_clear()


def test_evening_digest_pending_before_hour(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("on1y.digest.evening.digest_hour_reached", lambda **_: False)
    client = TestClient(create_app())
    resp = client.get("/api/digest/evening")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is True
    assert body["reason"] == "before_digest_hour"
    assert body["digest_date"] == today_digest_date()


def test_evening_digest_archive(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        "on1y.digest.evening.generate_evening_llm_summary",
        lambda *_a, **_k: (None, "llm_not_configured"),
    )
    client = TestClient(create_app())
    try:
        client.post("/api/digest/evening/generate?day=2026-06-01&force=true")
        client.post("/api/digest/evening/generate?day=2026-06-02&force=true")
        arch = client.get("/api/digest/evening/archive")
        assert arch.status_code == 200
        dates = arch.json()["dates"]
        assert "2026-06-02" in dates
        assert "2026-06-01" in dates
        hist = client.get("/api/digest/evening?day=2026-06-01")
        assert hist.status_code == 200
        assert hist.json()["digest_date"] == "2026-06-01"
    finally:
        get_settings.cache_clear()


def test_evening_digest_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_DB_PATH", str(tmp_path / "test.db"))
    from on1y.config import get_settings

    get_settings.cache_clear()

    def _no_llm(*_a, **_k):
        return "Test summary.", None

    monkeypatch.setattr("on1y.digest.evening.generate_evening_llm_summary", _no_llm)
    client = TestClient(create_app())
    today = today_digest_date()
    try:
        gen = client.post(f"/api/digest/evening/generate?day={today}&force=true")
        assert gen.status_code == 200
        body = gen.json()
        assert body["llm_summary"] == "Test summary."

        status = client.get("/api/digest/evening/status")
        assert status.status_code == 200
        st = status.json()
        assert st["today_available"] is True
        assert st["today_unread"] is True

        read = client.post("/api/digest/evening/read", json={"day": today})
        assert read.status_code == 200
        assert read.json()["unread"] is False
    finally:
        get_settings.cache_clear()
