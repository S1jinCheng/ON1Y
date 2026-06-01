"""Base class for extractors with shared utilities."""

from __future__ import annotations

import abc
import logging
import re

from on1y.config import get_settings
from on1y.exceptions import ExtractionError
from on1y.models.enums import ContentType, ExtractStatus
from on1y.models.extract import ExtractResult

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\n{3,}")


class BaseExtractor(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def can_handle(self, url: str) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def extract(self, url: str) -> ExtractResult:
        raise NotImplementedError

    def _normalize_text(self, text: str) -> str:
        cleaned = text.replace("\r\n", "\n").strip()
        cleaned = _WHITESPACE.sub("\n\n", cleaned)
        max_chars = get_settings().max_body_chars
        if len(cleaned) > max_chars:
            return cleaned[:max_chars]
        return cleaned

    def _fail(self, url: str, message: str, *, platform: str) -> ExtractionError:
        logger.warning("Extraction failed for %s: %s", url, message)
        return ExtractionError(message, url=url, platform=platform)

    def _partial(
        self,
        *,
        platform: str,
        raw_title: str | None,
        body_text: str,
        content_type: ContentType,
        reason: str,
        author: str | None = None,
        author_avatar: str | None = None,
        author_url: str | None = None,
    ) -> ExtractResult:
        return ExtractResult(
            platform=platform,
            raw_title=raw_title,
            body_text=self._normalize_text(body_text),
            content_type=content_type,
            extract_status=ExtractStatus.PARTIAL,
            extract_error=reason,
            author=author,
            author_avatar=author_avatar,
            author_url=author_url,
        )

    def _ok(
        self,
        *,
        platform: str,
        raw_title: str | None,
        body_text: str,
        content_type: ContentType,
        author: str | None = None,
        author_avatar: str | None = None,
        author_url: str | None = None,
    ) -> ExtractResult:
        normalized = self._normalize_text(body_text)
        if not normalized.strip():
            raise ExtractionError("Empty body after normalization", url="", platform=platform)
        return ExtractResult(
            platform=platform,
            raw_title=raw_title,
            body_text=normalized,
            content_type=content_type,
            extract_status=ExtractStatus.OK,
            author=author,
            author_avatar=author_avatar,
            author_url=author_url,
        )
