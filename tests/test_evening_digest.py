"""Evening digest aggregation and API."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient
from on1y.auth.context import user_context
from on1y.digest.evening import (
    aggregate_evening_stats,
    build_evening_digest,
    generate_evening_llm_summary,
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


def test_aggregate_evening_stats_focus_priority(storage, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    monkeypatch.setenv("ON1Y_EVENING_DIGEST_MAX_CRUX", "3")
    monkeypatch.setenv("ON1Y_EVENING_DIGEST_FOCUS_DOMAINS", "economics,news")
    from on1y.config import get_settings

    get_settings.cache_clear()
    day = date.today().isoformat()
    fake_rows = [
        {
            "raw_id": 1,
            "title": "宏观经济信号变化",
            "platform": "zhihu",
            "summary": "经济数据出现新的收缩信号，需要尽快关注。",
            "is_read": False,
            "theme_slug": "economics",
            "theme_name_zh": "经济",
            "theme_name_en": "Economics",
            "meta": {"published": f"{day}T09:00:00+08:00"},
            "ingested_at": f"{day}T09:10:00+08:00",
            "updated_at": f"{day}T09:10:00+08:00",
        },
        {
            "raw_id": 2,
            "title": "科技产业融资节奏变化",
            "platform": "twitter",
            "summary": "科技投资方向出现分化。",
            "is_read": False,
            "theme_slug": "technology",
            "theme_name_zh": "科技",
            "theme_name_en": "Technology",
            "meta": {"published": f"{day}T10:00:00+08:00"},
            "ingested_at": f"{day}T10:10:00+08:00",
            "updated_at": f"{day}T10:10:00+08:00",
        },
        {
            "raw_id": 3,
            "title": "时政新规落地",
            "platform": "zhihu",
            "summary": "监管新规开始实施。",
            "is_read": True,
            "theme_slug": "news",
            "theme_name_zh": "新闻",
            "theme_name_en": "News",
            "meta": {"published": f"{day}T12:00:00+08:00"},
            "ingested_at": f"{day}T12:10:00+08:00",
            "updated_at": f"{day}T12:10:00+08:00",
        },
        {
            "raw_id": 4,
            "title": "游戏测评更新",
            "platform": "bilibili",
            "summary": "游戏更新内容。",
            "is_read": False,
            "theme_slug": "games",
            "theme_name_zh": "游戏",
            "theme_name_en": "Games",
            "meta": {"published": f"{day}T08:00:00+08:00"},
            "ingested_at": f"{day}T08:30:00+08:00",
            "updated_at": f"{day}T08:30:00+08:00",
        },
    ]
    monkeypatch.setattr("on1y.digest.evening._fetch_rows_for_digest", lambda _s: fake_rows)
    monkeypatch.setattr("on1y.digest.evening._count_unread_feed", lambda _s: 0)
    try:
        stats = aggregate_evening_stats(storage, day=day)
        assert len(stats["highlights"]) == 3
        assert stats["selection_meta"]["focus_selected_count"] >= 2
        assert stats["selection_meta"]["focus_quota"] == 2
        assert all("score" in item for item in stats["highlights"])
    finally:
        get_settings.cache_clear()


def test_generate_evening_digest_markdown_prompt(monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_EVENING_DIGEST_MAX_CRUX", "4")
    monkeypatch.setenv("ON1Y_EVENING_DIGEST_MAX_CHARS", "560")
    from on1y.config import get_settings

    get_settings.cache_clear()
    captured: dict[str, str | int] = {}

    class DummyClient:
        def chat(self, system: str, user: str, max_tokens: int) -> str:
            captured["system"] = system
            captured["user"] = user
            captured["max_tokens"] = max_tokens
            return "# 今日晚报 | 2026-06-01\n**一句话总览**\n## 今日Crux\n- **[经济]** ..."

    monkeypatch.setattr(
        "on1y.llm.settings.resolve_llm_settings",
        lambda: SimpleNamespace(api_key_set=True),
    )
    monkeypatch.setattr("on1y.llm.client.get_llm_client", lambda: DummyClient())
    try:
        summary, err = generate_evening_llm_summary(
            {
                "digest_date": "2026-06-01",
                "published_total": 5,
                "marked_read": 2,
                "notes_saved": 1,
                "unread_total": 9,
                "by_platform": [],
                "by_theme": [],
                "highlights": [],
            },
            locale="zh",
        )
        assert err is None
        assert summary is not None and summary.startswith("# 今日晚报")
        assert "仅输出 Markdown" in str(captured["system"])
        assert "不要强行使用“国内/国际/科技”等固定分区" in str(captured["system"])
        assert "主语 + 动作 + 核心结果" in str(captured["system"])
        assert "细节行格式必须是：细节：..." in str(captured["system"])
        assert "[ref](URL)" in str(captured["system"])
        assert "selection_meta" in str(captured["user"])
    finally:
        get_settings.cache_clear()
