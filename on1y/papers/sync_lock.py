"""Process-local coordination for Paper imports and synchronizers."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_guard = threading.Lock()
_user_locks: dict[int, threading.RLock] = {}


def _lock_for(user_id: int) -> threading.RLock:
    with _guard:
        return _user_locks.setdefault(user_id, threading.RLock())


@contextmanager
def paper_sync_lock(user_id: int) -> Iterator[None]:
    """Serialize folder and Zotero imports for one user."""

    lock = _lock_for(user_id)
    with lock:
        yield