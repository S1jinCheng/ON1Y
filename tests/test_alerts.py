"""Tests for pipeline alert classification and emission."""

from on1y.alerts import (
    AlertKind,
    classify_pipeline_error,
    emit_alert,
    list_alerts,
    acknowledge_alerts,
)


def test_classify_rate_limit() -> None:
    assert classify_pipeline_error("HTTP Error 429: Too Many Requests") == AlertKind.RATE_LIMIT


def test_classify_antibot() -> None:
    assert classify_pipeline_error("Zhihu blocked automated browser (security verification)") == AlertKind.ANTIBOT


def test_classify_none() -> None:
    assert classify_pipeline_error("network timeout") is None


def test_emit_alert_writes_log(tmp_path, monkeypatch) -> None:
    from on1y.config import get_settings

    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    alert = emit_alert(
        AlertKind.RATE_LIMIT,
        "youtube",
        "HTTP Error 429",
        worker="subtitles",
        url="https://www.youtube.com/watch?v=x",
    )
    assert alert is not None
    assert alert["kind"] == "rate_limit"
    rows = list_alerts(limit=5)
    assert len(rows) == 1
    active = list_alerts(limit=5, active_only=True)
    assert len(active) == 1

    acknowledge_alerts(clear_all=True)
    assert list_alerts(active_only=True) == []

    get_settings.cache_clear()
