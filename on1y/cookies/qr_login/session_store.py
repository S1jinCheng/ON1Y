"""In-memory QR login session store (single-user desktop / local serve)."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

SESSION_TTL_SECONDS = 180


@dataclass
class QrLoginSession:
    platform: str
    session_id: str
    user_id: int
    created_at: float
    expires_at: float
    qr_content: str | None
    hint: str
    method: str  # app_scan | browser
    status: str = "pending"  # pending | scanned | success | expired | error
    message: str | None = None
    account: dict[str, Any] | None = None
    import_result: dict[str, Any] | None = None
    _holder: Any = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        holder = self._holder
        if holder is None:
            return
        close_fn = getattr(holder, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass


_lock = threading.Lock()
_sessions: dict[str, QrLoginSession] = {}


def _purge_expired() -> None:
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if s.expires_at < now]
    for sid in expired:
        session = _sessions.pop(sid, None)
        if session is not None:
            session.close()


def create_session(
    *,
    platform: str,
    user_id: int,
    qr_content: str | None,
    hint: str,
    method: str,
    holder: Any,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> QrLoginSession:
    _purge_expired()
    session_id = secrets.token_urlsafe(16)
    now = time.time()
    session = QrLoginSession(
        platform=platform,
        session_id=session_id,
        user_id=user_id,
        created_at=now,
        expires_at=now + ttl_seconds,
        qr_content=qr_content,
        hint=hint,
        method=method,
        _holder=holder,
    )
    with _lock:
        _sessions[session_id] = session
    return session


def get_session(session_id: str) -> QrLoginSession | None:
    with _lock:
        _purge_expired()
        return _sessions.get(session_id)


def pop_session(session_id: str) -> QrLoginSession | None:
    with _lock:
        session = _sessions.pop(session_id, None)
        return session


def cancel_session(session_id: str) -> bool:
    with _lock:
        session = _sessions.pop(session_id, None)
    if session is None:
        return False
    session.close()
    return True
