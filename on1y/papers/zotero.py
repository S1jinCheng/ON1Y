"""Import bibliographic metadata and optional PDFs through Zotero API v3."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.papers.knowledge_sync import prepare_paper
from on1y.papers.local_sync import safe_pdf_name, validate_pdf
from on1y.papers.models import (
    PaperAuthor,
    PaperCollection,
    PaperCreate,
    PaperItem,
    PaperUpdate,
)
from on1y.papers.settings_store import PaperSettings, resolve_paper_cache_dir
from on1y.papers.shelf import create_paper, find_matching_paper, update_paper
from on1y.papers.sync_lock import paper_sync_lock

PAPER_ITEM_TYPES = {
    "journalArticle",
    "conferencePaper",
    "preprint",
    "report",
    "thesis",
    "bookSection",
}


def _headers(settings: PaperSettings) -> dict[str, str]:
    headers = {"Zotero-API-Version": "3", "Accept": "application/json"}
    if settings.zotero_api_key:
        headers["Zotero-API-Key"] = settings.zotero_api_key
    return headers


def _prefix(settings: PaperSettings) -> str:
    return f"{settings.zotero_library_type}/{settings.zotero_library_id or '0'}"


def _base(settings: PaperSettings) -> str:
    return settings.zotero_base_url.rstrip("/")


def _year(value: str) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", value or "")
    return int(match.group(0)) if match else None


def _authors(data: dict[str, Any]) -> list[PaperAuthor]:
    result: list[PaperAuthor] = []
    for creator in data.get("creators") or []:
        if creator.get("creatorType") not in {"author", "bookAuthor"}:
            continue
        name = str(creator.get("name") or "").strip()
        if not name:
            name = " ".join(
                value
                for value in [
                    str(creator.get("firstName") or "").strip(),
                    str(creator.get("lastName") or "").strip(),
                ]
                if value
            )
        if name:
            result.append(PaperAuthor(name=name))
    return result


def _tags(data: dict[str, Any]) -> list[str]:
    return [
        str(row.get("tag") or "").strip()
        for row in data.get("tags") or []
        if str(row.get("tag") or "").strip()
    ]


def _merge_tags(existing: list[str], incoming: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        name = value.strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _venue(data: dict[str, Any]) -> str | None:
    for key in ("publicationTitle", "conferenceName", "university", "institution", "seriesTitle"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return None


def _find_pdf_attachment_key(
    client: httpx.Client, settings: PaperSettings, parent_key: str
) -> str | None:
    children_url = f"{_base(settings)}/{_prefix(settings)}/items/{parent_key}/children"
    response = client.get(children_url, params={"format": "json"})
    response.raise_for_status()
    attachments = response.json()
    for attachment in attachments if isinstance(attachments, list) else []:
        data = attachment.get("data") or {}
        content_type = str(data.get("contentType") or "").lower()
        filename = str(data.get("filename") or "").lower()
        if content_type != "application/pdf" and not filename.endswith(".pdf"):
            continue
        key = str(attachment.get("key") or data.get("key") or "").strip()
        if key:
            return key
    return None


def _download_pdf_by_key(
    client: httpx.Client,
    settings: PaperSettings,
    user_id: int,
    attachment_key: str,
    title: str,
) -> str:
    destination = resolve_paper_cache_dir(user_id, settings.cache_dir) / safe_pdf_name(title)
    if destination.exists():
        try:
            validate_pdf(destination)
            return str(destination.resolve())
        except ValueError:
            pass
    index = 2
    original_stem = destination.stem
    while destination.exists():
        destination = destination.with_name(f"{original_stem} ({index}).pdf")
        index += 1
    file_url = f"{_base(settings)}/{_prefix(settings)}/items/{attachment_key}/file"
    if settings.zotero_mode == "local":
        path_response = client.get(f"{file_url}/view/url")
        path_response.raise_for_status()
        parsed = urlparse(path_response.text.strip())
        source_value = unquote(parsed.path)
        if parsed.netloc:
            source_value = f"//{parsed.netloc}{source_value}"
        elif re.match(r"^/[A-Za-z]:/", source_value):
            source_value = source_value[1:]
        source = Path(source_value)
        if not source.is_file():
            raise FileNotFoundError(f"Zotero attachment not found: {source}")
        shutil.copyfile(source, destination)
    else:
        file_response = client.get(file_url)
        file_response.raise_for_status()
        destination.write_bytes(file_response.content)
    try:
        validate_pdf(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return str(destination.resolve())


def _download_pdf(
    client: httpx.Client, settings: PaperSettings, user_id: int, parent_key: str, title: str
) -> str | None:
    attachment_key = _find_pdf_attachment_key(client, settings, parent_key)
    if not attachment_key:
        return None
    return _download_pdf_by_key(client, settings, user_id, attachment_key, title)


def _fetch_pages(
    client: httpx.Client,
    base_path: str,
    *,
    item_type: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    page_size = 100
    while start < 5000:
        params: dict[str, Any] = {
            "format": "json",
            "limit": page_size,
            "start": start,
        }
        if item_type:
            params["itemType"] = item_type
        response = client.get(base_path, params=params)
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            break
        rows.extend(row for row in page if isinstance(row, dict))
        if len(page) < page_size:
            break
        start += page_size
    return rows


def _fetch_items(client: httpx.Client, base_path: str) -> list[dict[str, Any]]:
    return _fetch_pages(client, base_path, item_type="-attachment")


def _collection_index(rows: list[dict[str, Any]]) -> dict[str, PaperCollection]:
    raw: dict[str, tuple[str, str | None]] = {}
    for row in rows:
        data = row.get("data") or {}
        key = str(row.get("key") or data.get("key") or "").strip()
        if not key:
            continue
        name = str(data.get("name") or key).strip() or key
        parent_value = data.get("parentCollection")
        parent_key = str(parent_value).strip() if isinstance(parent_value, str) else None
        raw[key] = (name, parent_key or None)

    result: dict[str, PaperCollection] = {}

    def resolve(key: str, visiting: set[str]) -> PaperCollection:
        if key in result:
            return result[key]
        name, parent_key = raw.get(key, (key, None))
        path = name
        safe_parent = parent_key if parent_key and parent_key != key else None
        if safe_parent and safe_parent not in visiting:
            parent = resolve(safe_parent, {*visiting, key})
            path = f"{parent.path} / {name}"
        collection = PaperCollection(
            key=key,
            name=name,
            path=path,
            parent_key=safe_parent,
        )
        result[key] = collection
        return collection

    for key in raw:
        resolve(key, set())
    return result


def _collections_for_item(
    data: dict[str, Any], collection_index: dict[str, PaperCollection]
) -> list[PaperCollection]:
    result: list[PaperCollection] = []
    seen: set[str] = set()
    for value in data.get("collections") or []:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(
            collection_index.get(key)
            or PaperCollection(key=key, name=key, path=key)
        )
    return sorted(result, key=lambda row: (row.path.casefold(), row.key))


def _merge_payload(
    existing: PaperItem,
    *,
    title: str,
    authors: list[PaperAuthor],
    abstract: str | None,
    year: int | None,
    venue: str | None,
    doi: str | None,
    url: str | None,
    pdf_path: str | None,
    tags: list[str],
    zotero_collections: list[PaperCollection] | None,
    zotero_key: str,
    zotero_library_id: str,
    zotero_attachment_key: str | None,
    zotero_library_type: str,
    zotero_version: int | None,
) -> PaperUpdate:
    values: dict[str, Any] = {
        "title": title or existing.title,
        "authors": authors or existing.authors,
        "abstract": abstract or existing.abstract,
        "year": year or existing.year,
        "venue": venue or existing.venue,
        "doi": doi or existing.doi,
        "url": url or existing.url,
        "pdf_path": pdf_path or existing.pdf_path,
        "tags": _merge_tags(existing.tags, tags),
        "zotero_key": zotero_key,
        "zotero_library_id": zotero_library_id,
        "zotero_attachment_key": zotero_attachment_key,
        "zotero_library_type": zotero_library_type,
        "zotero_version": zotero_version,
    }
    if zotero_collections is not None:
        values["zotero_collections"] = zotero_collections
    return PaperUpdate.model_validate(values)


def sync_zotero(
    storage: SqliteStorage,
    user_id: int,
    settings: PaperSettings,
) -> dict[str, Any]:
    if not settings.zotero_enabled:
        return {
            "enabled": False,
            "imported": 0,
            "updated": 0,
            "downloaded": 0,
            "errors": [],
        }
    imported = 0
    updated = 0
    downloaded = 0
    errors: list[str] = []
    base_path = (
        f"{_base(settings)}/{_prefix(settings)}/collections/"
        f"{settings.zotero_collection_key}/items/top"
        if settings.zotero_collection_key
        else f"{_base(settings)}/{_prefix(settings)}/items/top"
    )
    with (
        paper_sync_lock(user_id),
        httpx.Client(
            headers=_headers(settings),
            timeout=30,
            follow_redirects=True,
        ) as client,
    ):
        collections_loaded = True
        collection_index: dict[str, PaperCollection] = {}
        try:
            collection_rows = _fetch_pages(
                client,
                f"{_base(settings)}/{_prefix(settings)}/collections",
            )
            collection_index = _collection_index(collection_rows)
        except Exception as exc:
            collections_loaded = False
            errors.append(f"Zotero 分类读取失败（已保留原分类）: {exc}")
        rows = _fetch_items(client, base_path)
        for row in rows:
            data = row.get("data") or {}
            if data.get("itemType") not in PAPER_ITEM_TYPES:
                continue
            key = str(row.get("key") or data.get("key") or "").strip()
            title = str(data.get("title") or "").strip()
            if not key or not title:
                continue
            try:
                authors = _authors(data)
                year = _year(str(data.get("date") or ""))
                doi = str(data.get("DOI") or "").strip() or None
                existing = find_matching_paper(
                    storage,
                    user_id,
                    zotero_library_id=settings.zotero_library_id,
                    zotero_key=key,
                    doi=doi,
                    title=title,
                    year=year,
                    authors=authors,
                )
                pdf_path = existing.pdf_path if existing else None
                attachment_key = existing.zotero_attachment_key if existing else None
                if not attachment_key:
                    try:
                        attachment_key = _find_pdf_attachment_key(client, settings, key)
                    except Exception as exc:
                        errors.append(f"{title}: Zotero attachment {exc}")
                if settings.zotero_download_pdfs and not pdf_path and attachment_key:
                    try:
                        pdf_path = _download_pdf_by_key(
                            client, settings, user_id, attachment_key, title
                        )
                        downloaded += 1
                    except Exception as exc:
                        errors.append(f"{title}: PDF {exc}")
                abstract = str(data.get("abstractNote") or "").strip() or None
                venue = _venue(data)
                url = str(data.get("url") or "").strip() or None
                tags = _tags(data)
                zotero_collections = (
                    _collections_for_item(data, collection_index)
                    if collections_loaded
                    else None
                )
                version = int(row.get("version") or data.get("version") or 0) or None
                if existing:
                    item = update_paper(
                        storage,
                        user_id,
                        existing.id,
                        _merge_payload(
                            existing,
                            title=title,
                            authors=authors,
                            abstract=abstract,
                            year=year,
                            venue=venue,
                            doi=doi,
                            url=url,
                            pdf_path=pdf_path,
                            tags=tags,
                            zotero_collections=zotero_collections,
                            zotero_key=key,
                            zotero_library_id=settings.zotero_library_id,
                            zotero_attachment_key=attachment_key,
                            zotero_library_type=settings.zotero_library_type,
                            zotero_version=version,
                        ),
                    )
                    updated += 1
                else:
                    item = create_paper(
                        storage,
                        user_id,
                        PaperCreate(
                            title=title,
                            authors=authors,
                            abstract=abstract,
                            year=year,
                            venue=venue,
                            doi=doi,
                            url=url,
                            pdf_path=pdf_path,
                            tags=tags,
                            zotero_collections=zotero_collections or [],
                            zotero_version=version,
                            zotero_key=key,
                            zotero_library_id=settings.zotero_library_id,
                            zotero_attachment_key=attachment_key,
                            zotero_library_type=settings.zotero_library_type,
                        ),
                    )
                    imported += 1
                if item:
                    prepare_paper(storage, user_id, item)
            except Exception as exc:
                errors.append(f"{title}: {exc}")
    return {
        "enabled": True,
        "imported": imported,
        "updated": updated,
        "downloaded": downloaded,
        "errors": errors,
    }
