"""LLM settings: .env defaults + optional data/llm_settings.json from web UI."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from on1y.auth.context import get_effective_user_id
from on1y.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class LlmSettings:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    max_input_chars: int

    @property
    def api_key_set(self) -> bool:
        return bool(self.api_key.strip())


def settings_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    from on1y.user.paths import user_llm_settings_path

    per_user = user_llm_settings_path(uid)
    if per_user.is_file() or uid != 1:
        return per_user
    legacy = get_settings().data_dir / "llm_settings.json"
    return legacy if legacy.is_file() else per_user


def load_file_settings(*, user_id: int | None = None) -> dict[str, Any]:
    path = settings_file_path(user_id=user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Invalid LLM settings file: %s", path)
        return {}


def save_file_settings(
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
    clear_api_key: bool = False,
    user_id: int | None = None,
) -> None:
    """Persist per-user UI settings. Empty api_key keeps existing key unless clear_api_key."""
    from on1y.user.paths import user_llm_settings_path

    uid = user_id if user_id is not None else get_effective_user_id()
    path = user_llm_settings_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_file_settings(user_id=uid)
    payload: dict[str, Any] = {
        "base_url": base_url.rstrip("/"),
        "model": model.strip(),
    }
    if clear_api_key:
        payload["api_key"] = ""
    elif api_key is not None and api_key.strip():
        payload["api_key"] = api_key.strip()
    elif current.get("api_key"):
        payload["api_key"] = current["api_key"]

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_llm_client_cache()
    logger.info("Saved LLM settings for user %s", uid)


def resolve_llm_settings(*, user_id: int | None = None) -> LlmSettings:
    """Merge per-user file settings over environment defaults."""
    settings = get_settings()
    file_cfg = load_file_settings(user_id=user_id)
    # Per-user file key takes precedence; fall back to the shared env key.
    api_key = str(file_cfg.get("api_key") or settings.llm_api_key or "").strip()
    base_url = str(file_cfg.get("base_url") or settings.llm_base_url or DEFAULT_BASE_URL).rstrip("/")
    model = str(file_cfg.get("model") or settings.llm_model or DEFAULT_MODEL).strip()
    return LlmSettings(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        max_input_chars=settings.llm_max_input_chars,
    )


def public_settings_view(*, user_id: int | None = None) -> dict[str, Any]:
    """Safe for API/UI — never returns full api_key."""
    cfg = resolve_llm_settings(user_id=user_id)
    key = cfg.api_key
    preview = ""
    if key:
        preview = key[:4] + "…" + key[-4:] if len(key) > 10 else "（已设置）"
    return {
        "base_url": cfg.base_url,
        "model": cfg.model,
        "api_key_set": cfg.api_key_set,
        "api_key_preview": preview,
        "defaults": {
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
        },
    }


def clear_llm_client_cache() -> None:
    from on1y.llm.client import _get_llm_client_cached

    _get_llm_client_cached.cache_clear()
    _resolve_llm_settings_cached.cache_clear()


@lru_cache(maxsize=64)
def _resolve_llm_settings_cached(user_id: int) -> LlmSettings:
    return resolve_llm_settings(user_id=user_id)


def get_resolved_llm_settings() -> LlmSettings:
    return _resolve_llm_settings_cached(get_effective_user_id())
