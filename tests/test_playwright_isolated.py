"""Playwright isolation helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.browser.playwright_isolated import run_playwright_isolated


def test_run_playwright_isolated_on_clean_thread() -> None:
    assert run_playwright_isolated(lambda: 42) == 42


def test_run_playwright_isolated_when_loop_running() -> None:
    loop = MagicMock()
    loop.is_running.return_value = True
    with patch("asyncio.get_running_loop", return_value=loop):
        assert run_playwright_isolated(lambda: "ok") == "ok"
