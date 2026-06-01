"""Shared HTTP client for extractors."""

from __future__ import annotations

import httpx

from on1y.config import get_settings


def build_http_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; On1y/0.1; +https://github.com/on1y/on1y)"
            ),
        },
    )
