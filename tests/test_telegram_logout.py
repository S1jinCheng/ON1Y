"""Tests for Telegram session logout."""

from __future__ import annotations

from pathlib import Path

from on1y.telegram.client import avatar_file_path, logout_session, session_path


def test_logout_session_removes_files(tmp_path: Path, monkeypatch) -> None:
    user_id = 42
    monkeypatch.setattr(
        "on1y.telegram.client.user_dir",
        lambda uid: tmp_path if uid == user_id else tmp_path / str(uid),
    )
    monkeypatch.setattr("on1y.telegram.client.get_effective_user_id", lambda: user_id)

    session_file = session_path(user_id=user_id).with_suffix(".session")
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("session", encoding="utf-8")
    avatar = avatar_file_path(user_id=user_id)
    avatar.write_bytes(b"avatar")

    result = logout_session(user_id=user_id)

    assert result["ok"] is True
    assert not session_file.is_file()
    assert not avatar.is_file()
