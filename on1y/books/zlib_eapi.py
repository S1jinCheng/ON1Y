"""Z-Library mobile eapi client (httpx, no browser)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from on1y.books.edition_match import EditionHints
from on1y.books.zlib_links import BOOK_FORMATS
from on1y.books.zlib_session import ZlibSession
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=60.0, read=900.0, write=60.0, pool=60.0)


class ZlibEapiClient:
    def __init__(self, session: ZlibSession, *, timeout: float = 60.0) -> None:
        self._session = session
        self._timeout = timeout
        self._base = f"https://{session.host}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
            "remix-userid": self._session.remix_userid,
            "remix-userkey": self._session.remix_userkey,
        }

    def _cookies(self) -> dict[str, str]:
        return {
            "siteLanguageV2": "en",
            "remix_userid": self._session.remix_userid,
            "remix_userkey": self._session.remix_userkey,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            response = client.request(
                method,
                url,
                data=data,
                params=params,
                headers=self._headers(),
                cookies=self._cookies(),
            )
        if response.status_code >= 400:
            raise ConfigurationError(f"Z-Library HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise ConfigurationError("Z-Library 返回了非 JSON 响应（可能未登录或域名失效）") from exc
        if not isinstance(payload, dict):
            raise ConfigurationError("Z-Library 响应格式异常")
        if payload.get("success") is False:
            err = payload.get("error") or payload.get("message") or "request failed"
            raise ConfigurationError(f"Z-Library: {err}")
        return payload

    def verify(self) -> bool:
        try:
            payload = self._request("GET", "/eapi/user/profile")
            return bool(payload.get("success") and payload.get("user"))
        except Exception as exc:
            logger.debug("Z-Library verify failed: %s", exc)
            return False

    def profile(self) -> dict[str, Any]:
        return self._request("GET", "/eapi/user/profile")

    def search_books(
        self,
        query: str,
        fmt: str | None = None,
        *,
        limit: int = 25,
        order: str = "popular",
    ) -> list[dict[str, Any]]:
        data: dict[str, Any] = {
            "message": (query or "").strip(),
            "page": 1,
            "limit": limit,
            "order": order,
        }
        if fmt:
            data["extensions[]"] = fmt.lower()
        payload = self._request("POST", "/eapi/book/search", data=data)
        books = payload.get("books")
        if not isinstance(books, list):
            return []
        return [book for book in books if isinstance(book, dict) and book.get("id") and book.get("hash")]

    def search_popular(self, query: str, fmt: str | None = None, *, limit: int = 3) -> list[dict[str, Any]]:
        return self.search_books(query, fmt, limit=limit, order="popular")

    def search_first(self, title: str, fmt: str) -> dict[str, Any] | None:
        books = self.search_books(title, fmt, limit=10)
        return books[0] if books else None

    def search_best_across_formats(
        self,
        hints: EditionHints,
        formats: list[str],
        *,
        strategy: str,
        preferred_format: str,
    ) -> tuple[dict[str, Any], str, str]:
        from on1y.books.acquire_strategy import format_search_order, pick_zlib_candidate

        order = format_search_order(
            strategy=strategy,  # type: ignore[arg-type]
            preferred_format=preferred_format,
            allowed_formats=formats,
        )
        books_by_fmt: dict[str, list[dict[str, Any]]] = {}
        for fmt in order:
            books = self.search_books(hints.search_query(), fmt)
            if not books:
                books = self.search_books(hints.title, fmt)
            if books:
                books_by_fmt[fmt] = books
        pick = pick_zlib_candidate(
            books_by_fmt,
            hints,
            strategy=strategy,  # type: ignore[arg-type]
            preferred_format=preferred_format,
            format_order=order,
        )
        if pick is None:
            raise ConfigurationError(f"Z-Library 未找到「{hints.title}」的可用电子书")
        return pick.book, pick.quality, pick.fmt

    def download_bytes(self, book_id: str | int, book_hash: str) -> tuple[str, bytes]:
        dest_info = self._file_download_info(book_id, book_hash)
        headers = self._headers()
        parsed = urlparse(dest_info["download_link"])
        if parsed.netloc:
            headers["authority"] = parsed.netloc
        try:
            with httpx.Client(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                response = client.get(
                    dest_info["download_link"],
                    headers=headers,
                    cookies=self._cookies(),
                )
        except httpx.TimeoutException as exc:
            raise ConfigurationError(
                "Z-Library 下载超时（文件较大时请换较小版本或稍后重试）"
            ) from exc
        except httpx.HTTPError as exc:
            raise ConfigurationError(f"Z-Library 下载失败：{exc}") from exc
        if response.status_code >= 400:
            raise ConfigurationError(f"Z-Library 下载 HTTP {response.status_code}")
        data = response.content
        if len(data) < 1024:
            raise ConfigurationError("Z-Library 返回了空文件")
        return dest_info["filename"], data

    def download_to_path(self, book_id: str | int, book_hash: str, dest: Path) -> dict[str, Any]:
        """Stream download to disk (for large files)."""
        dest_info = self._file_download_info(book_id, book_hash)
        headers = self._headers()
        parsed = urlparse(dest_info["download_link"])
        if parsed.netloc:
            headers["authority"] = parsed.netloc
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                with client.stream(
                    "GET",
                    dest_info["download_link"],
                    headers=headers,
                    cookies=self._cookies(),
                ) as response:
                    if response.status_code >= 400:
                        raise ConfigurationError(f"Z-Library 下载 HTTP {response.status_code}")
                    with dest.open("wb") as handle:
                        for chunk in response.iter_bytes(1024 * 256):
                            if chunk:
                                handle.write(chunk)
        except httpx.TimeoutException as exc:
            dest.unlink(missing_ok=True)
            raise ConfigurationError(
                "Z-Library 下载超时（文件较大时请换较小版本或稍后重试）"
            ) from exc
        except httpx.HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise ConfigurationError(f"Z-Library 下载失败：{exc}") from exc
        size = dest.stat().st_size
        if size < 1024:
            dest.unlink(missing_ok=True)
            raise ConfigurationError("Z-Library 返回了空文件")
        return {
            "filename": dest_info["filename"],
            "extension": dest_info["extension"],
            "size_bytes": size,
        }

    def _file_download_info(self, book_id: str | int, book_hash: str) -> dict[str, str]:
        payload = self._request("GET", f"/eapi/book/{book_id}/{book_hash}/file")
        file_info = payload.get("file")
        if not isinstance(file_info, dict):
            raise ConfigurationError("Z-Library 未返回文件信息")
        download_link = str(file_info.get("downloadLink") or "").strip()
        if not download_link:
            raise ConfigurationError("Z-Library 未返回下载链接")
        extension = str(file_info.get("extension") or "bin").strip().lstrip(".")
        author = str(file_info.get("author") or "").strip()
        description = str(file_info.get("description") or "book").strip() or "book"
        filename = description
        if author:
            filename = f"{description} ({author})"
        filename = f"{filename}.{extension}"
        return {
            "download_link": download_link,
            "extension": extension,
            "filename": filename,
        }


def _zlib_cover_url(book: dict[str, Any], host: str) -> str | None:
    for key in ("cover", "img", "image"):
        value = book.get(key)
        if not value:
            continue
        url = str(value).strip()
        if not url:
            continue
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            return f"https://{host}{url}"
        return url
    return None


def _zlib_book_format(book: dict[str, Any]) -> str:
    ext = str(book.get("extension") or book.get("filetype") or "").lower().lstrip(".")
    if ext in BOOK_FORMATS:
        return ext
    return "epub"


def zlib_book_candidate(
    book: dict[str, Any],
    host: str,
    *,
    douban_cover: str | None = None,
) -> dict[str, Any]:
    return {
        "source": "zlib",
        "format": _zlib_book_format(book),
        "title": str(book.get("title") or "").strip(),
        "author": str(book.get("author") or "").strip() or None,
        "publisher": str(book.get("publisher") or "").strip() or None,
        "year": str(book.get("year") or "").strip() or None,
        "language": str(book.get("language") or "").strip() or None,
        "filesize": str(book.get("filesizeString") or book.get("filesize") or "").strip() or None,
        "cover_url": _zlib_cover_url(book, host) or douban_cover,
        "book_id": book["id"],
        "book_hash": book["hash"],
    }


def download_from_zlib_eapi(
    session: ZlibSession,
    *,
    hints: EditionHints,
    fmt: str | None = None,
    formats: list[str] | None = None,
    strategy: str = "match_first",
    preferred_format: str = "epub",
) -> tuple[bytes, dict[str, Any]]:
    del formats, strategy, preferred_format
    client = ZlibEapiClient(session)
    if not client.verify():
        raise ConfigurationError("Z-Library Cookie 无效，请在设置中重新导入 remix_userid / remix_userkey")
    books = client.search_popular(hints.search_query(), fmt=fmt, limit=1)
    if not books:
        books = client.search_popular(hints.title, fmt=fmt, limit=1)
    if not books:
        label = fmt.upper() if fmt else "任意格式"
        raise ConfigurationError(f"Z-Library 未找到「{hints.title}」的 {label} 结果")
    book = books[0]
    chosen_fmt = _zlib_book_format(book)
    _filename, data = client.download_bytes(book["id"], book["hash"])
    meta = {
        "matched_title": str(book.get("title") or hints.title),
        "matched_author": str(book.get("author") or "") or None,
        "search_query": hints.search_query(),
        "format": chosen_fmt,
    }
    return data, meta
