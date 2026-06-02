"""Password hashing with bcrypt."""

from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) < 8:
        raise ValueError("password must be at least 8 characters")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
