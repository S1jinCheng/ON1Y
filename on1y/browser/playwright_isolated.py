"""Run sync Playwright outside uvicorn's running asyncio loop."""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_playwright_isolated(fn: Callable[[], T]) -> T:
    """
    Execute sync Playwright work on a dedicated thread.

    FastAPI/uvicorn runs asyncio on the main thread; Playwright sync API uses
    greenlets and fails when ``loop.is_running()``. Background collection sync
    can hit the same failure on Windows — always use a clean worker thread.

    Request-scoped context (e.g. current user for cookie paths) is copied into
    the worker thread so callers can resolve per-user paths before Playwright runs.
    """
    ctx = contextvars.copy_context()
    result: list[T] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            result.append(ctx.run(fn))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker, name="on1y-playwright")
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]
