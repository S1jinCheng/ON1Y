"""Per-user SMTP settings for Kindle delivery."""

from __future__ import annotations

from on1y.auth.context import user_context
from on1y.delivery.smtp_settings import (
    load_file_settings,
    public_settings_view,
    resolve_smtp_settings,
    save_file_settings,
    settings_file_path,
)


def test_save_and_resolve_smtp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_SMTP_HOST", "env.smtp.test")
    monkeypatch.setenv("ON1Y_SMTP_USER", "env@example.com")
    monkeypatch.setenv("ON1Y_SMTP_PASSWORD", "env-secret")
    monkeypatch.setenv("ON1Y_SMTP_FROM", "env@example.com")
    from on1y.config import get_settings

    get_settings.cache_clear()

    with user_context(1):
        save_file_settings(
            host="smtp.gmail.com",
            port=587,
            user="me@gmail.com",
            password="abcd efgh ijkl mnop",
            from_addr="me@gmail.com",
            use_tls=True,
        )
        cfg = resolve_smtp_settings()
        assert cfg.host == "smtp.gmail.com"
        assert cfg.user == "me@gmail.com"
        assert cfg.password == "abcdefghijklmnop"
        assert cfg.configured is True

        view = public_settings_view()
        assert view["password_set"] is True
        assert view["configured"] is True
        assert settings_file_path().is_file()


def test_user2_does_not_inherit_env_password(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_SMTP_PASSWORD", "env-only")
    from on1y.config import get_settings

    get_settings.cache_clear()

    with user_context(2):
        assert resolve_smtp_settings().password == ""
        assert resolve_smtp_settings().configured is False
        save_file_settings(user="u2@example.com", password="user2-pass", from_addr="u2@example.com")
        cfg = resolve_smtp_settings()
        assert cfg.password == "user2-pass"
        assert load_file_settings()["user"] == "u2@example.com"
