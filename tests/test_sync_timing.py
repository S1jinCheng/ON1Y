"""Sync timing helpers."""

from on1y.sync.timing import (
    build_timing_record,
    format_duration_ms,
    rollup_phase_totals,
)


def test_format_duration_ms():
    assert format_duration_ms(4500) == "4s"
    assert format_duration_ms(65_000) == "1m05s"
    assert format_duration_ms(3_661_000) == "1h01m"


def test_rollup_phase_totals():
    spans = {
        "collections.bilibili": 1200.0,
        "collections.zhihu": 800.0,
        "subscriptions.bilibili.poll": 5000.0,
        "pipeline.bilibili.distill": 9000.0,
        "pipeline.youtube.enrich": 3000.0,
    }
    rolled = rollup_phase_totals(spans)
    assert rolled["collections"] == 2000.0
    assert rolled["subscriptions"] == 5000.0
    assert rolled["pipeline"] == 12000.0


def test_build_timing_record():
    record = build_timing_record(
        user_id=1,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:10:00+00:00",
        phases_ms={"collections": 1000, "subscriptions": 2000, "pipeline": 3000},
        detail={"spans_ms": {"collections.bilibili": 1000}},
    )
    assert record["total_ms"] == 6000.0
    assert record["total_human"] == "6s"
    assert record["phases_human"]["pipeline"] == "3s"
