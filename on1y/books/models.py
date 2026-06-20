"""Pydantic models for the books module."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

BookStatus = Literal["reading", "read"]
BookSourceType = Literal["link", "fetch"]
BookHitKind = Literal["link", "edition"]


class BookLink(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)


class BookShortReview(BaseModel):
    author: str | None = None
    content: str = Field(min_length=1, max_length=4000)
    published_at: str | None = None

class BookSource(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    type: BookSourceType = "link"
    enabled: bool = True
    url_template: str = Field(min_length=1, max_length=2048)
    parser: str | None = None
    sort_order: int = 0

    @field_validator("id")
    @classmethod
    def _id_chars(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.replace("-", "").replace("_", "").isalnum():
            raise ValueError("source id must be alphanumeric (dash/underscore allowed)")
        return cleaned


class BookSourcesFile(BaseModel):
    version: int = 1
    sources: list[BookSource] = Field(default_factory=list)


class BookSearchHit(BaseModel):
    source_id: str
    source_name: str
    query: str
    url: str
    kind: BookHitKind = "link"


class BookEditionHit(BaseModel):
    edition_id: str
    source_id: str
    source_name: str
    title: str
    author: str | None = None
    translator: str | None = None
    publisher: str | None = None
    pub_meta: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    cover_url: str | None = None
    url: str
    kind: BookHitKind = "edition"


class BookWorkDetail(BaseModel):
    edition_id: str
    title: str
    author: str | None = None
    translator: str | None = None
    publisher: str | None = None
    pub_date: str | None = None
    isbn: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    cover_url: str | None = None
    summary: str | None = None
    short_reviews: list[BookShortReview] = Field(default_factory=list)
    url: str
    acquisition_links: list[BookLink] = Field(default_factory=list)
    source_links: list[BookLink] = Field(default_factory=list)


def parse_cached_path(notes: str | None) -> str | None:
    for line in (notes or "").splitlines():
        if line.strip().lower().startswith("cached:"):
            return line.split(":", 1)[1].strip() or None
    return None


class BookShelfItem(BaseModel):
    id: int
    raw_id: int | None = None
    title: str
    author: str | None = None
    translator: str | None = None
    publisher: str | None = None
    cover_url: str | None = None
    summary: str | None = None
    status: BookStatus = "reading"
    links: list[BookLink] = Field(default_factory=list)
    notes: str | None = None
    user_note_html: str | None = None
    importance: int | None = None
    theme_slug: str | None = None
    tags: list[str] = Field(default_factory=list)
    cached_format: str | None = None
    local_path: str | None = None
    created_at: str
    updated_at: str


class BookShelfCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=300)
    translator: str | None = Field(default=None, max_length=300)
    publisher: str | None = Field(default=None, max_length=300)
    cover_url: str | None = Field(default=None, max_length=2048)
    summary: str | None = Field(default=None, max_length=8000)
    status: BookStatus = "reading"
    links: list[BookLink] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=20_000)
    cached_format: str | None = Field(default=None, max_length=16)
    tags: list[str] = Field(default_factory=list)


class BookShelfUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=300)
    translator: str | None = Field(default=None, max_length=300)
    publisher: str | None = Field(default=None, max_length=300)
    cover_url: str | None = Field(default=None, max_length=2048)
    summary: str | None = Field(default=None, max_length=8000)
    status: BookStatus | None = None
    links: list[BookLink] | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    user_note_html: str | None = Field(default=None, max_length=200_000)
    importance: int | None = Field(default=None, ge=1, le=5)
    theme_slug: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    cached_format: str | None = Field(default=None, max_length=16)


def shelf_item_from_row(row: Any) -> BookShelfItem:
    from on1y.utils.json_util import loads_json_list

    links_raw = loads_json_list(row["links_json"] if row["links_json"] else "[]")
    links = [BookLink.model_validate(item) for item in links_raw if isinstance(item, dict)]
    tags_raw = loads_json_list(row["tags_json"] if "tags_json" in row.keys() and row["tags_json"] else "[]")
    tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    notes = str(row["notes"]) if row["notes"] else None
    keys = row.keys()
    return BookShelfItem(
        id=int(row["id"]),
        raw_id=int(row["raw_id"]) if "raw_id" in keys and row["raw_id"] is not None else None,
        title=str(row["title"]),
        author=str(row["author"]) if row["author"] else None,
        translator=str(row["translator"]) if "translator" in keys and row["translator"] else None,
        publisher=str(row["publisher"]) if "publisher" in keys and row["publisher"] else None,
        cover_url=str(row["cover_url"]) if "cover_url" in keys and row["cover_url"] else None,
        summary=str(row["summary"]) if "summary" in keys and row["summary"] else None,
        status=row["status"],
        links=links,
        notes=notes,
        user_note_html=str(row["user_note_html"]) if "user_note_html" in keys and row["user_note_html"] else None,
        importance=int(row["importance"]) if "importance" in keys and row["importance"] is not None else None,
        theme_slug=str(row["theme_slug"]) if "theme_slug" in keys and row["theme_slug"] else None,
        tags=tags,
        cached_format=str(row["cached_format"]) if "cached_format" in keys and row["cached_format"] else None,
        local_path=parse_cached_path(notes),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
