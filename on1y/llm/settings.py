"""LLM settings: .env defaults + optional data/llm_settings.json from web UI."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

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


def settings_file_path() -> Path:
    return get_settings().data_dir / "llm_settings.json"


def load_file_settings() -> dict[str, Any]:
    path = settings_file_path()
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
) -> None:
    """Persist UI settings. Empty api_key keeps existing key unless clear_api_key."""
    path = settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_file_settings()
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
    logger.info("Saved LLM settings to %s", path)


def resolve_llm_settings() -> LlmSettings:
    """Merge file settings (web UI) over environment defaults."""
    settings = get_settings()
    file_cfg = load_file_settings()
    api_key = str(settings.llm_api_key or file_cfg.get("api_key") or "").strip()
    base_url = str(file_cfg.get("base_url") or settings.llm_base_url or DEFAULT_BASE_URL).rstrip("/")
    model = str(file_cfg.get("model") or settings.llm_model or DEFAULT_MODEL).strip()
    return LlmSettings(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        max_input_chars=settings.llm_max_input_chars,
    )


def public_settings_view() -> dict[str, Any]:
    """Safe for API/UI — never returns full api_key."""
    cfg = resolve_llm_settings()
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
    from on1y.llm.client import get_llm_client

    get_llm_client.cache_clear()
    get_resolved_llm_settings.cache_clear()


@lru_cache
def get_resolved_llm_settings() -> LlmSettings:
    return resolve_llm_settings()
