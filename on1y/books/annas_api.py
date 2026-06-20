"""Anna's Archive search + download via HTTP API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from on1y.books.builtin_sources import ANNAS_BASE
from on1y.books.edition_match import EditionHints, match_quality, pick_best_index
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

_MD5_RE = re.compile(r"/md5/([a-f0-9]{32})", re.IGNORECASE)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class AnnasArchiveClient:
    def __init__(self, *, base_url: str = ANNAS_BASE, timeout: float = 90.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/json"},
        )

    def search_candidates(self, query: str, fmt: str | None = None) -> list[tuple[str, str]]:
        q = quote((query or "").strip())
        if fmt:
            url = f"{self._base}/search?q={q}&ext={quote(fmt.lower())}"
        else:
            url = f"{self._base}/search?q={q}"
        with self._client() as client:
            response = client.get(url)
        if response.status_code >= 400:
            raise ConfigurationError(f"安娜档案搜索 HTTP {response.status_code}")
        html = response.text
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()
        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.select("a[href*='/md5/']"):
            href = anchor.get("href") or ""
            md5_match = _MD5_RE.search(href)
            if not md5_match:
                continue
            md5 = md5_match.group(1).lower()
            if md5 in seen:
                continue
            seen.add(md5)
            label = (anchor.get_text(" ", strip=True) or "")[:300]
            parent = anchor.parent
            if parent is not None:
                label = (parent.get_text(" ", strip=True) or label)[:500]
            candidates.append((md5, label))
        if not candidates:
            for match in _MD5_RE.finditer(html):
                md5 = match.group(1).lower()
                if md5 not in seen:
                    candidates.append((md5, ""))
                    seen.add(md5)
        return candidates

    def search_md5(self, title: str, fmt: str) -> str | None:
        candidates = self.search_candidates(title, fmt)
        return candidates[0][0] if candidates else None

    def search_best_across_formats(
        self,
        hints: EditionHints,
        formats: list[str],
        *,
        strategy: str,
        preferred_format: str,
    ) -> tuple[str, str, str, str]:
        from on1y.books.acquire_strategy import format_search_order, pick_annas_candidate

        order = format_search_order(
            strategy=strategy,  # type: ignore[arg-type]
            preferred_format=preferred_format,
            allowed_formats=formats,
        )
        by_fmt: dict[str, list[tuple[str, str]]] = {}
        for fmt in order:
            rows = self.search_candidates(hints.search_query(), fmt)
            if not rows:
                rows = self.search_candidates(hints.title, fmt)
            if rows:
                by_fmt[fmt] = rows
        pick = pick_annas_candidate(
            by_fmt,
            hints,
            strategy=strategy,  # type: ignore[arg-type]
            preferred_format=preferred_format,
            format_order=order,
        )
        if pick is None:
            raise ConfigurationError(f"安娜档案未找到「{hints.title}」的可用电子书")
        return pick.md5, pick.label, pick.quality, pick.fmt

    def fast_download_url(self, md5: str, secret_key: str) -> str:
        params = {"md5": md5, "key": secret_key.strip()}
        url = f"{self._base}/dyn/api/fast_download.json"
        with self._client() as client:
            response = client.get(url, params=params)
        if response.status_code >= 400:
            raise ConfigurationError(f"安娜档案 fast_download HTTP {response.status_code}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ConfigurationError("安娜档案 fast_download 返回非 JSON（可能需要会员密钥）") from exc
        if not isinstance(payload, dict):
            raise ConfigurationError("安娜档案 fast_download 响应异常")
        error = payload.get("error")
        if error:
            raise ConfigurationError(f"安娜档案: {error}")
        download_url = str(payload.get("download_url") or "").strip()
        if not download_url:
            raise ConfigurationError("安娜档案未返回下载链接")
        return download_url

    def partner_download_urls(self, md5: str) -> list[str]:
        url = f"{self._base}/md5/{md5}"
        with self._client() as client:
            response = client.get(url)
        if response.status_code >= 400:
            raise ConfigurationError(f"安娜档案书籍页 HTTP {response.status_code}")
        html = response.text
        urls: list[str] = []
        seen: set[str] = set()

        def add(raw: str) -> None:
            cleaned = raw.strip()
            if not cleaned or cleaned in seen:
                return
            if not cleaned.startswith("http"):
                cleaned = urljoin(self._base, cleaned)
            if cleaned.startswith("http"):
                seen.add(cleaned)
                urls.append(cleaned)

        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "")
            text = (anchor.get_text() or "").lower()
            if "/dl/" in href or "/slow_download/" in href or "download" in text:
                add(href)
        for match in re.finditer(r'https?://[^\s"\'<>]+/(?:dl|slow_download)/[^\s"\'<>]+', html):
            add(match.group(0))
        return urls

    def download_file(self, download_url: str) -> bytes:
        headers = {"User-Agent": _USER_AGENT}
        timeout = httpx.Timeout(60.0, connect=60.0, read=900.0, write=60.0, pool=60.0)
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/json"},
            ) as client:
                response = client.get(download_url, headers=headers)
        except httpx.TimeoutException as exc:
            raise ConfigurationError("安娜档案下载超时（文件较大时请换较小版本）") from exc
        except httpx.HTTPError as exc:
            raise ConfigurationError(f"安娜档案下载失败：{exc}") from exc
        if response.status_code >= 400:
            raise ConfigurationError(f"安娜档案下载 HTTP {response.status_code}")
        data = response.content
        if len(data) < 1024:
            raise ConfigurationError("安娜档案返回了空文件")
        return data


def download_from_annas(
    *,
    hints: EditionHints,
    fmt: str | None = None,
    formats: list[str] | None = None,
    strategy: str = "match_first",
    preferred_format: str = "epub",
    secret_key: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    del formats, strategy, preferred_format
    client = AnnasArchiveClient()
    candidates = client.search_candidates(hints.search_query(), fmt)
    if not candidates:
        candidates = client.search_candidates(hints.title, fmt)
    if not candidates:
        label = fmt.upper() if fmt else "任意格式"
        raise ConfigurationError(f"安娜档案未找到「{hints.title}」的 {label} 结果")
    md5, label = candidates[0]
    chosen_fmt = fmt or "epub"
    meta = {
        "matched_title": label[:200] or hints.title,
        "matched_author": None,
        "search_query": hints.search_query(),
        "md5": md5,
        "format": chosen_fmt,
    }

    errors: list[str] = []
    if secret_key and secret_key.strip():
        try:
            url = client.fast_download_url(md5, secret_key)
            return client.download_file(url), meta
        except ConfigurationError as exc:
            errors.append(str(exc))

    for url in client.partner_download_urls(md5):
        try:
            return client.download_file(url), meta
        except ConfigurationError as exc:
            errors.append(str(exc))
            logger.debug("Anna partner download failed %s: %s", url, exc)

    hint = "；".join(errors[:2]) if errors else "无可用镜像"
    raise ConfigurationError(
        f"安娜档案下载失败（{hint}）。"
        "可在设置 → 图书填写安娜档案会员 Secret Key 以使用 fast_download API"
    )
