"""SMTP settings: .env defaults + per-user data/users/<id>/smtp_settings.json."""

from __future__ import annotations

import json
import logging
import smtplib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from on1y.auth.context import get_effective_user_id
from on1y.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_HOST = "smtp.gmail.com"
DEFAULT_PORT = 587


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    user: str
    password: str
    from_addr: str
    use_tls: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password and self.from_addr)


def settings_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    from on1y.user.paths import user_smtp_settings_path

    return user_smtp_settings_path(uid)


def load_file_settings(*, user_id: int | None = None) -> dict[str, Any]:
    path = settings_file_path(user_id=user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Invalid SMTP settings file: %s", path)
        return {}


def save_file_settings(
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    from_addr: str | None = None,
    use_tls: bool | None = None,
    clear_password: bool = False,
    user_id: int | None = None,
) -> None:
    uid = user_id if user_id is not None else get_effective_user_id()
    from on1y.user.paths import user_smtp_settings_path

    path = user_smtp_settings_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_file_settings(user_id=uid)
    payload = dict(current)

    if host is not None:
        payload["host"] = host.strip()
    if port is not None:
        payload["port"] = max(1, min(65535, int(port)))
    if user is not None:
        payload["user"] = user.strip()
    if from_addr is not None:
        payload["from"] = from_addr.strip()
    if use_tls is not None:
        payload["use_tls"] = bool(use_tls)
    if clear_password:
        payload["password"] = ""
    elif password is not None and password.strip():
        payload["password"] = password.replace(" ", "").strip()
    elif current.get("password"):
        payload["password"] = current["password"]

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _resolve_smtp_settings_cached.cache_clear()
    logger.info("Saved SMTP settings for user %s", uid)


def resolve_smtp_settings(*, user_id: int | None = None) -> SmtpSettings:
    settings = get_settings()
    uid = user_id if user_id is not None else get_effective_user_id()
    file_cfg = load_file_settings(user_id=uid)

    def pick_str(key: str, env_val: str | None) -> str:
        if key in file_cfg and str(file_cfg[key]).strip():
            return str(file_cfg[key]).strip()
        if uid == 1 and env_val:
            return str(env_val).strip()
        return ""

    def pick_password() -> str:
        file_pw = str(file_cfg.get("password") or "").replace(" ", "").strip()
        if file_pw:
            return file_pw
        if uid == 1:
            return str(settings.smtp_password or "").replace(" ", "").strip()
        return ""

    host = pick_str("host", settings.smtp_host) or DEFAULT_HOST
    port_raw = file_cfg.get("port")
    if port_raw is not None and str(port_raw).strip():
        port = int(port_raw)
    elif uid == 1:
        port = int(settings.smtp_port)
    else:
        port = DEFAULT_PORT

    user = pick_str("user", settings.smtp_user)
    from_addr = pick_str("from", settings.smtp_from or settings.smtp_user)
    if not from_addr and user:
        from_addr = user

    if "use_tls" in file_cfg:
        use_tls = bool(file_cfg["use_tls"])
    elif uid == 1:
        use_tls = bool(settings.smtp_use_tls)
    else:
        use_tls = True

    return SmtpSettings(
        host=host,
        port=port,
        user=user,
        password=pick_password(),
        from_addr=from_addr,
        use_tls=use_tls,
    )


def public_settings_view(*, user_id: int | None = None) -> dict[str, Any]:
    cfg = resolve_smtp_settings(user_id=user_id)
    settings = get_settings()
    return {
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.user,
        "from": cfg.from_addr,
        "use_tls": cfg.use_tls,
        "password_set": bool(cfg.password),
        "configured": cfg.configured,
        "defaults": {
            "host": DEFAULT_HOST,
            "port": DEFAULT_PORT,
            "use_tls": True,
        },
        "env_configured": bool(
            settings.smtp_host and settings.smtp_user and settings.smtp_password
        ),
    }


def test_smtp_connection(
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    from_addr: str | None = None,
    use_tls: bool | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    saved = resolve_smtp_settings(user_id=user_id)
    cfg = SmtpSettings(
        host=(host or saved.host).strip(),
        port=int(port if port is not None else saved.port),
        user=(user or saved.user).strip(),
        password=(password or saved.password).replace(" ", "").strip(),
        from_addr=(from_addr or saved.from_addr).strip(),
        use_tls=use_tls if use_tls is not None else saved.use_tls,
    )
    if not cfg.configured:
        return {"ok": False, "error": "SMTP 未配置完整（主机、账号、密码、发件人）"}
    try:
        if cfg.use_tls:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(cfg.user, cfg.password)
        else:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=30) as smtp:
                smtp.login(cfg.user, cfg.password)
        return {"ok": True, "from": cfg.from_addr, "host": cfg.host}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@lru_cache(maxsize=64)
def _resolve_smtp_settings_cached(user_id: int) -> SmtpSettings:
    return resolve_smtp_settings(user_id=user_id)


def get_resolved_smtp_settings() -> SmtpSettings:
    return _resolve_smtp_settings_cached(get_effective_user_id())
