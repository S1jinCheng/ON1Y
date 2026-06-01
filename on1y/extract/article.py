"""Generic article extractor — Jina Reader with BeautifulSoup fallback."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from on1y.config import get_settings
from on1y.extract.base import BaseExtractor
from on1y.extract.http_client import build_http_client
from on1y.models.enums import ContentType
from on1y.models.extract import ExtractResult
from on1y.utils.platform import detect_platform

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


class ArticleExtractor(BaseExtractor):
    """Fallback for non-video URLs; also handles Zhihu, blogs, GitHub pages."""

    @property
    def name(self) -> str:
        return "article"

    def can_handle(self, url: str) -> bool:
        # Video platforms have dedicated extractors; this handles everything else.
        from on1y.utils.platform import (
            PLATFORM_BILIBILI,
            PLATFORM_TWITTER,
            PLATFORM_XIAOHONGSHU,
            PLATFORM_YOUTUBE,
            PLATFORM_ZHIHU,
        )

        platform = detect_platform(url)
        return platform not in (
            PLATFORM_YOUTUBE,
            PLATFORM_BILIBILI,
            PLATFORM_ZHIHU,
            PLATFORM_XIAOHONGSHU,
            PLATFORM_TWITTER,
        )

    def extract(self, url: str) -> ExtractResult:
        platform = detect_platform(url)
        title: str | None = None
        body: str | None = None
        errors: list[str] = []

        try:
            title, body = self._fetch_jina(url)
        except Exception as exc:
            errors.append(f"jina: {exc}")
            logger.debug("Jina Reader failed for %s: %s", url, exc)

        if not body or len(body.strip()) < 100:
            try:
                title_bs, body_bs = self._fetch_beautifulsoup(url)
                if body_bs and len(body_bs.strip()) >= len((body or "").strip()):
                    title = title or title_bs
                    body = body_bs
            except Exception as exc:
                errors.append(f"bs4: {exc}")
                logger.debug("BeautifulSoup failed for %s: %s", url, exc)

        if not body or not body.strip():
            raise self._fail(
                url,
                "Could not extract article text: " + "; ".join(errors),
                platform=platform,
            )

        status = "ok" if len(body.strip()) >= 200 and not errors else "partial"
        if status == "partial":
            return self._partial(
                platform=platform,
                raw_title=title,
                body_text=body,
                content_type=ContentType.ARTICLE,
                reason="; ".join(errors) or "short_content",
            )
        return self._ok(
            platform=platform,
            raw_title=title,
            body_text=body,
            content_type=ContentType.ARTICLE,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _fetch_jina(self, url: str) -> tuple[str | None, str]:
        settings = get_settings()
        reader_url = f"{settings.jina_reader_base}{url}"
        with build_http_client() as client:
            response = client.get(reader_url)
            response.raise_for_status()
            text = response.text.strip()

        title = _extract_markdown_title(text)
        return title, text

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    def _fetch_beautifulsoup(self, url: str) -> tuple[str | None, str]:
        with build_http_client() as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else None
        article = soup.find("article")
        root = article if article else soup.find("main") or soup.body
        if root is None:
            return title, ""
        paragraphs = [
            p.get_text(" ", strip=True) for p in root.find_all(["p", "h1", "h2", "h3", "li"])
        ]
        body = "\n\n".join(p for p in paragraphs if p)
        return title, body


def _extract_markdown_title(markdown: str) -> str | None:
    for line in markdown.splitlines()[:20]:
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
        if s.startswith("Title:"):
            return s[6:].strip()
    return None
