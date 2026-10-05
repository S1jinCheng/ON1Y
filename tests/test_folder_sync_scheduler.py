from __future__ import annotations

import threading
import time
from pathlib import Path

from on1y.folder_sync.scheduler import SyncScheduler, notify_folder_sync


def test_scheduler_runs_immediately_and_stops_promptly(tmp_path: Path) -> None:
    ran = threading.Event()
    scheduler = SyncScheduler(
        tmp_path / "on1y.db",
        runner=lambda _path: ran.set(),
        fingerprint=lambda _path: "steady",
        poll_interval=0.02,
        debounce=0.02,
        fallback_interval=10,
    )

    scheduler.start()
    assert ran.wait(0.5)
    scheduler.stop(timeout=0.5)

    assert not scheduler.is_alive


def test_notification_during_sync_schedules_a_follow_up(tmp_path: Path) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    follow_up_finished = threading.Event()
    calls = 0

    def runner(_path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            assert release_first.wait(0.5)
        elif calls == 2:
            follow_up_finished.set()

    scheduler = SyncScheduler(
        tmp_path / "on1y.db",
        runner=runner,
        fingerprint=lambda _path: "steady",
        poll_interval=0.01,
        debounce=0.02,
        fallback_interval=10,
    )
    scheduler.start()
    try:
        assert first_started.wait(0.5)
        notify_folder_sync("test-write-during-sync")
        release_first.set()
        assert follow_up_finished.wait(0.5)
    finally:
        release_first.set()
        scheduler.stop(timeout=0.5)

    assert calls == 2


def test_scheduler_does_not_retrigger_on_its_own_database_write(tmp_path: Path) -> None:
    first_finished = threading.Event()
    fingerprint_version = 0
    calls = 0

    def fingerprint(_path: Path) -> int:
        return fingerprint_version

    def runner(_path: Path) -> None:
        nonlocal calls, fingerprint_version
        calls += 1
        fingerprint_version += 1
        first_finished.set()

    scheduler = SyncScheduler(
        tmp_path / "on1y.db",
        runner=runner,
        fingerprint=fingerprint,
        poll_interval=0.01,
        debounce=0.02,
        fallback_interval=10,
    )
    scheduler.start()
    try:
        assert first_finished.wait(0.5)
        time.sleep(0.12)
    finally:
        scheduler.stop(timeout=0.5)

    assert calls == 1


def test_scheduler_uses_progressive_failure_backoff(tmp_path: Path) -> None:
    attempts: list[float] = []
    fourth_attempt = threading.Event()

    def failing_runner(_path: Path) -> None:
        attempts.append(time.monotonic())
        if len(attempts) == 4:
            fourth_attempt.set()
        raise RuntimeError("offline")

    scheduler = SyncScheduler(
        tmp_path / "on1y.db",
        runner=failing_runner,
        fingerprint=lambda _path: "steady",
        poll_interval=0.01,
        debounce=0.01,
        fallback_interval=10,
        failure_delays=(0.03, 0.06, 0.09),
    )
    scheduler.start()
    try:
        assert fourth_attempt.wait(1.0)
    finally:
        scheduler.stop(timeout=0.5)

    gaps = [later - earlier for earlier, later in zip(attempts, attempts[1:], strict=False)]
    assert gaps[0] >= 0.02
    assert gaps[1] >= 0.05
    assert gaps[2] >= 0.08
