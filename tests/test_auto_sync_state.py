from datetime import datetime, timezone

from on1y.sync.auto_sync_state import should_backfill_after_gap


def test_should_backfill_after_gap_same_day() -> None:
    from on1y.sync import auto_sync_state as mod

    user_id = 99_001
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    mod.write_last_auto_sync_at(user_id=user_id, at=datetime(2026, 6, 8, 1, 0, tzinfo=timezone.utc))
    assert should_backfill_after_gap(user_id=user_id, now=now) is False


def test_should_backfill_after_gap_previous_day() -> None:
    from on1y.sync import auto_sync_state as mod

    user_id = 99_002
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    mod.write_last_auto_sync_at(user_id=user_id, at=datetime(2026, 6, 7, 23, 0, tzinfo=timezone.utc))
    assert should_backfill_after_gap(user_id=user_id, now=now) is True


def test_should_backfill_after_gap_no_history() -> None:
    assert should_backfill_after_gap(user_id=99_003) is False
