"""Request-scoped current user (web) and explicit overrides (CLI / background jobs)."""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

_current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "on1y_current_user_id", default=None
)


def get_current_user_id() -> int | None:
    return _current_user_id.get()


def set_current_user_id(user_id: int | None) -> None:
    _current_user_id.set(user_id)


def get_effective_user_id(*, default: int = 1) -> int:
    uid = get_current_user_id()
    return uid if uid is not None else default


@contextlib.contextmanager
def user_context(user_id: int) -> Iterator[None]:
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)
