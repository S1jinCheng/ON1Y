"""Translate English video transcripts to Chinese via LLM."""

from __future__ import annotations

import logging
import time

from on1y.config import get_settings
from on1y.exceptions import ConfigurationError
from on1y.llm.client import get_llm_client
from on1y.utils.transcript_meta import classify_transcript, extract_transcript_plain

logger = logging.getLogger(__name__)

_TRANSLATE_SYSTEM = """You are a professional translator.
Translate the user's video transcript from English to Simplified Chinese.
Preserve paragraph breaks. Output plain Chinese prose only — no markdown headers, no commentary."""


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        block = para.strip()
        if not block:
            continue
        candidate = f"{buf}\n\n{block}".strip() if buf else block
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            parts.append(buf)
            buf = ""
        if len(block) <= max_chars:
            buf = block
            continue
        for i in range(0, len(block), max_chars):
            parts.append(block[i : i + max_chars])
    if buf:
        parts.append(buf)
    return parts


def translate_body_to_zh(
    body: str,
    *,
    title: str | None = None,
) -> str:
    kind = classify_transcript(body)
    if kind == "none":
        raise ValueError("item has no subtitle transcript to translate")
    if kind == "zh":
        raise ValueError("transcript is already Chinese")

    plain = extract_transcript_plain(body)
    if not plain.strip():
        raise ValueError("empty transcript text")

    settings = get_settings()
    client = get_llm_client()
    chunk_size = min(settings.llm_distill_max_input_chars // 2, 12_000)
    chunks = _chunk_text(plain, chunk_size)
    translated_parts: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        prefix = f"(Part {idx}/{len(chunks)})\n" if len(chunks) > 1 else ""
        user = f"{prefix}{chunk}"
        part = ""
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                part = client.chat(
                    _TRANSLATE_SYSTEM,
                    user,
                    max_tokens=min(settings.llm_max_output_tokens * 2, 4096),
                )
            except ConfigurationError as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except Exception as exc:
                raise ConfigurationError(f"translation failed on chunk {idx}: {exc}") from exc
            if part.strip():
                break
            last_exc = ConfigurationError("LLM returned empty content")
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
        if not part.strip():
            raise ConfigurationError(f"translation failed on chunk {idx}: {last_exc}") from last_exc
        translated_parts.append(part.strip())
        logger.info("Translated chunk %s/%s (%s chars)", idx, len(chunks), len(chunk))

    translated = "\n\n".join(translated_parts).strip()
    header = "## 字幕（中文 · 机器翻译）"
    if title:
        return f"# {title.strip()}\n\n{header}\n\n{translated}"
    return f"{header}\n\n{translated}"
