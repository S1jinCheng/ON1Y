"""OpenAI-compatible chat completions client."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

import httpx

from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def resolve_chat_completions_url(base_url: str) -> str:
    """Build OpenAI-compatible chat/completions URL from a provider base URL."""
    base = base_url.strip().rstrip("/")
    if not base:
        raise ConfigurationError("LLM Base URL 不能为空")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/chat/completions"


class LlmClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.strip().rstrip("/")
        self._chat_url = resolve_chat_completions_url(self._base_url)
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Return parsed JSON object from model response."""
        text = self.chat(system, user, max_tokens=max_tokens, json_mode=True)
        return _parse_json_response(text)

    def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        if not self._api_key:
            raise ConfigurationError(
                "未配置 LLM API Key。请在 Web 控制台「LLM 设置」填写，或设置 ON1Y_LLM_API_KEY"
            )
        url = self._chat_url
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.is_error:
                raise ConfigurationError(_format_api_error(response))
            data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ConfigurationError("LLM returned empty choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content or not str(content).strip():
            raise ConfigurationError("LLM returned empty content")
        return str(content).strip()


def _format_api_error(response: httpx.Response) -> str:
    """Turn HTTP error bodies (e.g. DeepSeek 401) into a short user message."""
    try:
        body = response.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict) and err.get("message"):
            msg = str(err["message"])
            if response.status_code == 401:
                return (
                    f"API Key 无效或未授权（401）：{msg}。"
                    "请确认 Key 来自 https://platform.deepseek.com ，"
                    "Base URL 为 https://api.deepseek.com ，模型如 deepseek-v4-flash。"
                )
            return f"LLM 请求失败（{response.status_code}）：{msg}"
    except (json.JSONDecodeError, ValueError):
        pass
    return f"LLM 请求失败（{response.status_code}）：{response.text[:300]}"


def _parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    match = _JSON_BLOCK_RE.search(text)
    if match:
        text = match.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigurationError("LLM JSON root must be an object")
    return parsed


@lru_cache(maxsize=64)
def _get_llm_client_cached(user_id: int) -> LlmClient:
    from on1y.llm.settings import resolve_llm_settings

    cfg = resolve_llm_settings(user_id=user_id)
    if not cfg.api_key_set:
        raise ConfigurationError(
            "未配置 LLM API Key。请在「设置 → AI 模型」保存 API Key，或设置 ON1Y_LLM_API_KEY"
        )
    return LlmClient(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model,
        timeout=cfg.timeout_seconds,
    )


def get_llm_client() -> LlmClient:
    from on1y.auth.context import get_effective_user_id

    return _get_llm_client_cached(get_effective_user_id())
