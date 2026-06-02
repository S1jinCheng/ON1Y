"""JWT access tokens for the web API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from on1y.config import get_settings


def create_access_token(*, user_id: int, username: str) -> str:
    settings = get_settings()
    secret = (settings.auth_secret_key or "").strip()
    if not secret or secret == "change-me-in-production":
        pass  # local dev may use default; production should set ON1Y_AUTH_SECRET_KEY
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=settings.auth_token_ttl_hours)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "usr": username,
        "iat": int(now.timestamp()),
        "exp": exp,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    secret = (settings.auth_secret_key or "").strip()
    return jwt.decode(token, secret, algorithms=["HS256"])
