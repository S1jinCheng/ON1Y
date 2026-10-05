"""Change-aware background scheduling for the two desktop sync transports.

Stat-only hints trigger sync without opening user documents or downloading an
iCloud placeholder. Both transports retain their own locking and durable state.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import stat
import threading
import time
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_NOTIFY_LOCK = threading.Lock()
_NOTIFY_SEQUENCE = 0
_NOTIFY_REASON = "startup"
_SUBSCRIBERS: set[threading.Event] = set()


def notify_folder_sync(reason: str = "manual") -> None:
    """Wake the scheduler after an in-process data or settings change."""
    global _NOTIFY_REASON, _NOTIFY_SEQUENCE
    with _NOTIFY_LOCK:
        _NOTIFY_SEQUENCE += 1
        _NOTIFY_REASON = str(reason or "manual")[:100]
        subscribers = tuple(_SUBSCRIBERS)
    for wake in subscribers:
        wake.set()


def _notification_snapshot() -> tuple[int, str]:
    with _NOTIFY_LOCK:
        return _NOTIFY_SEQUENCE, _NOTIFY_REASON


def _subscribe(wake: threading.Event) -> None:
    with _NOTIFY_LOCK:
        _SUBSCRIBERS.add(wake)


def _unsubscribe(wake: threading.Event) -> None:
    with _NOTIFY_LOCK:
        _SUBSCRIBERS.discard(wake)


def _stat_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


@dataclass(frozen=True)
class _FolderSources:
    enabled: bool = False
    user_id: int | None = None
    protocol_folder: str = ""
    literature_enabled: bool = False
    literature_vault_path: str = ""


def _read_folder_sources(db_path: Path) -> _FolderSources:
    """Read optional folder-sync configuration without creating a database."""
    if not db_path.is_file():
        return _FolderSources()
    try:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=0.1) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='folder_sync_config'"
            ).fetchone()
            if not table:
                return _FolderSources()
            columns = {row[1] for row in conn.execute("PRAGMA table_info(folder_sync_config)")}
            wanted = ["user_id", "folder", "enabled"]
            wanted.extend(
                name
                for name in ("literature_files_enabled", "literature_vault_path")
                if name in columns
            )
            row = conn.execute(
                f"SELECT {','.join(wanted)} FROM folder_sync_config WHERE id=1"
            ).fetchone()
    except (OSError, sqlite3.Error, ValueError):
        return _FolderSources()
    if not row:
        return _FolderSources()
    values = dict(zip(wanted, row, strict=True))
    enabled = bool(values.get("enabled"))
    literature_enabled = enabled and bool(values.get("literature_files_enabled"))
    vault = str(values.get("literature_vault_path") or "")
    user_id = int(values["user_id"])
    if literature_enabled and not vault:
        try:
            from on1y.papers.settings_store import resolve_literature_vault

            vault = str(resolve_literature_vault(user_id))
        except (OSError, ValueError):
            vault = ""
    return _FolderSources(
        enabled=enabled,
        user_id=user_id,
        protocol_folder=str(values.get("folder") or ""),
        literature_enabled=literature_enabled,
        literature_vault_path=vault,
    )


_SKIP_DIRECTORIES = {
    ".git",
    ".stfolder",
    ".sync",
    ".trash",
    ".trashes",
    "__pycache__",
    "_system",
}
_SKIP_FILES = {".ds_store", "desktop.ini", "thumbs.db"}


def _fallback_literature_files(root: Path) -> Iterable[Path]:
    """Yield ordinary Vault files when the tree-sync module is unavailable."""
    pending = [root]
    while pending:
        folder = pending.pop()
        try:
            entries = tuple(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            lowered = name.casefold()
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if lowered not in _SKIP_DIRECTORIES:
                        pending.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if (
                lowered in _SKIP_FILES
                or lowered.startswith("~$")
                or lowered.endswith((".db-wal", ".db-shm", ".db-journal", ".ffs_tmp"))
                or (lowered.startswith("workspace") and folder.name.casefold() == ".obsidian")
            ):
                continue
            yield Path(entry.path)


def _iter_literature_files(root: Path) -> Iterable[Path]:
    try:
        from on1y.folder_sync.literature_tree import iter_sync_files
    except (ImportError, AttributeError):
        yield from _fallback_literature_files(root)
        return

    for entry in iter_sync_files(root):
        if isinstance(entry, (str, os.PathLike)):
            candidate = Path(entry)
        elif isinstance(entry, tuple):
            candidates = [Path(value) for value in entry if isinstance(value, (str, os.PathLike))]
            if not candidates:
                continue
            candidate = next(
                (value for value in candidates if value.is_absolute() and value.is_file()),
                candidates[0],
            )
        else:
            continue
        yield candidate if candidate.is_absolute() else root / candidate


def _literature_signature(root: Path) -> tuple[int, str] | None:
    if not root.is_dir():
        return None
    items: list[tuple[str, Path]] = []
    try:
        resolved_root = root.resolve(strict=True)
        for path in _iter_literature_files(resolved_root):
            try:
                resolved = path.resolve(strict=False)
                relative = resolved.relative_to(resolved_root).as_posix()
            except (OSError, ValueError):
                continue
            items.append((relative, resolved))
    except OSError:
        return None

    digest = hashlib.blake2b(digest_size=16)
    count = 0
    for relative, path in sorted(items, key=lambda item: (item[0].casefold(), item[0])):
        try:
            info = path.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        digest.update(relative.encode("utf-8", errors="surrogatepass"))
        digest.update(b"\0")
        digest.update(
            f"{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_mode}".encode()
        )
        digest.update(b"\0")
        count += 1
    return count, digest.hexdigest()


def sync_fingerprint(db_path: Path) -> Hashable:
    """Return stat-only change hints for local data and the cloud protocol."""
    db_path = Path(db_path)
    sources = _read_folder_sources(db_path)
    events = None
    literature_events = None
    literature_seeds = None
    objects = None
    if sources.enabled and sources.protocol_folder:
        events = _stat_signature(Path(sources.protocol_folder) / "events")
        literature_events = _stat_signature(
            Path(sources.protocol_folder) / "literature-events"
        )
        literature_seeds = _stat_signature(
            Path(sources.protocol_folder) / "literature-seeds"
        )
        objects = _stat_signature(Path(sources.protocol_folder) / "objects")
    literature = None
    if sources.literature_enabled and sources.literature_vault_path:
        literature = _literature_signature(Path(sources.literature_vault_path))
    return (
        _stat_signature(db_path),
        _stat_signature(Path(str(db_path) + "-wal")),
        events,
        literature_events,
        literature_seeds,
        objects,
        literature,
    )


def run_sync_cycle(db_path: Path) -> None:
    """Run relay then folder sync serially, retaining the first failure."""
    if not db_path.is_file():
        return
    from on1y.device_sync.client import run_sync
    from on1y.folder_sync.engine import run_folder_sync

    failure: Exception | None = None
    try:
        run_sync(db_path)
    except Exception as exc:  # The transport persists its safe UI error.
        failure = exc
    try:
        run_folder_sync(db_path)
    except Exception as exc:  # Let one transport run even if the other failed.
        failure = failure or exc
    if failure is not None:
        raise failure


class SyncScheduler:
    """One-thread scheduler with debounce, fallback, and bounded retry timing."""

    def __init__(
        self,
        db_path: Path,
        *,
        runner: Callable[[Path], Any] = run_sync_cycle,
        fingerprint: Callable[[Path], Hashable] = sync_fingerprint,
        clock: Callable[[], float] = time.monotonic,
        poll_interval: float = 3.0,
        debounce: float = 1.0,
        fallback_interval: float = 30.0,
        failure_delays: tuple[float, ...] = (5.0, 15.0, 30.0),
    ) -> None:
        if not failure_delays or min(
            poll_interval, debounce, fallback_interval, *failure_delays
        ) <= 0:
            raise ValueError("scheduler intervals must be positive")
        self.db_path = Path(db_path)
        self.runner = runner
        self.fingerprint = fingerprint
        self.clock = clock
        self.poll_interval = poll_interval
        self.debounce = debounce
        self.fallback_interval = fallback_interval
        self.failure_delays = failure_delays
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.is_alive:
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self.run_forever,
            name="on1y-sync-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Wake the loop and wait at most ``timeout`` for a running sync."""
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(max(0.0, timeout))

    def _fingerprint(self) -> Hashable:
        try:
            return self.fingerprint(self.db_path)
        except Exception as exc:
            # A transient lock/disconnected drive is itself a state change; the
            # periodic run will persist the actionable transport error.
            return ("fingerprint-error", type(exc).__name__, str(exc)[:100])

    def run_forever(self) -> None:
        _subscribe(self._wake)
        fingerprint = self._fingerprint()
        notice, _ = _notification_snapshot()
        pending_since: float | None = None
        next_poll = self.clock()
        next_fallback = self.clock()  # Startup sync is immediate.
        retry_at: float | None = None
        failures = 0
        try:
            while not self._stop.is_set():
                now = self.clock()
                current_notice, _ = _notification_snapshot()
                if current_notice != notice:
                    notice = current_notice
                    pending_since = now

                if now >= next_poll:
                    current = self._fingerprint()
                    if current != fingerprint:
                        fingerprint = current
                        pending_since = now
                    next_poll = now + self.poll_interval

                change_due = pending_since is not None and now >= pending_since + self.debounce
                scheduled_due = now >= next_fallback
                retry_due = retry_at is not None and now >= retry_at
                can_run = retry_at is None or retry_due
                if can_run and (change_due or scheduled_due or retry_due):
                    notice_before, _ = _notification_snapshot()
                    pending_since = None
                    try:
                        self.runner(self.db_path)
                    except Exception:
                        failures += 1
                        delay = self.failure_delays[min(failures - 1, len(self.failure_delays) - 1)]
                        retry_at = self.clock() + delay
                        logger.warning("Background sync failed; retrying in %.0f seconds", delay)
                    else:
                        failures = 0
                        retry_at = None
                        completed = self.clock()
                        next_fallback = completed + self.fallback_interval
                        after = self._fingerprint()
                        fingerprint = after
                        notice_after, _ = _notification_snapshot()
                        if notice_after != notice_before:
                            notice = notice_after
                            pending_since = completed
                    continue

                deadlines = [next_poll]
                if retry_at is not None:
                    deadlines.append(retry_at)
                else:
                    deadlines.append(next_fallback)
                    if pending_since is not None:
                        deadlines.append(pending_since + self.debounce)
                wait_for = max(0.0, min(deadlines) - self.clock())
                self._wake.wait(wait_for)
                self._wake.clear()
        finally:
            _unsubscribe(self._wake)
