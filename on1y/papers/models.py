"""Pydantic models for the paper library."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, field_validator

PaperStatus = Literal["to_read", "reading", "read"]


class PaperAiSummary(BaseModel):
    overview: str = ""
    research_question: str = ""
    method: str = ""
    key_findings: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class PaperFigure(BaseModel):
    filename: str
    page: int = Field(ge=1)
    caption: str = ""
    kind: Literal["figure", "table"] = "figure"
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class PaperCollection(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=500)
    path: str = Field(min_length=1, max_length=2000)
    parent_key: str | None = Field(default=None, max_length=100)


class PaperAuthor(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    scholar_id: str | None = Field(default=None, max_length=200)
    scholar_url: str | None = Field(default=None, max_length=2048)

    @property
    def google_scholar_url(self) -> str:
        if self.scholar_url:
            return self.scholar_url
        if self.scholar_id:
            return f"https://scholar.google.com/citations?user={quote_plus(self.scholar_id)}"
        return f"https://scholar.google.com/scholar?q=author%3A%22{quote_plus(self.name)}%22"


class PaperItemBase(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    authors: list[PaperAuthor] = Field(default_factory=list)
    abstract: str | None = Field(default=None, max_length=50_000)
    status: PaperStatus = "to_read"
    year: int | None = Field(default=None, ge=1000, le=3000)
    venue: str | None = Field(default=None, max_length=500)
    doi: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2048)
    pdf_path: str | None = Field(default=None, max_length=4096)
    citation_count: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list)

    @field_validator("authors", mode="before")
    @classmethod
    def _coerce_authors(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [{"name": row} if isinstance(row, str) else row for row in value]


class PaperCreate(PaperItemBase):
    zotero_collections: list[PaperCollection] = Field(default_factory=list)
    zotero_key: str | None = Field(default=None, max_length=100)
    zotero_library_id: str | None = Field(default=None, max_length=100)
    zotero_attachment_key: str | None = Field(default=None, max_length=100)
    zotero_library_type: Literal["users", "groups"] | None = None
    zotero_version: int | None = None


class PaperUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    authors: list[PaperAuthor] | None = None
    abstract: str | None = Field(default=None, max_length=50_000)
    status: PaperStatus | None = None
    year: int | None = Field(default=None, ge=1000, le=3000)
    venue: str | None = Field(default=None, max_length=500)
    doi: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2048)
    pdf_path: str | None = Field(default=None, max_length=4096)
    citation_count: int | None = Field(default=None, ge=0)
    user_note_html: str | None = Field(default=None, max_length=200_000)
    importance: int | None = Field(default=None, ge=1, le=5)
    theme_slug: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    zotero_key: str | None = Field(default=None, max_length=100)
    zotero_library_id: str | None = Field(default=None, max_length=100)
    zotero_attachment_key: str | None = Field(default=None, max_length=100)
    zotero_library_type: Literal["users", "groups"] | None = None
    zotero_version: int | None = None
    zotero_collections: list[PaperCollection] | None = None


class PaperItem(PaperItemBase):
    id: int
    raw_id: int | None = None
    zotero_key: str | None = None
    zotero_library_id: str | None = None
    zotero_attachment_key: str | None = None
    zotero_library_type: Literal["users", "groups"] | None = None
    zotero_version: int | None = None
    zotero_collections: list[PaperCollection] = Field(default_factory=list)
    user_note_html: str | None = None
    importance: int | None = None
    theme_slug: str | None = None
    ai_summary: PaperAiSummary | None = None
    ai_summary_status: Literal["idle", "running", "ok", "error"] = "idle"
    ai_summary_error: str | None = None
    ai_summary_model: str | None = None
    ai_summary_updated_at: str | None = None
    figures: list[PaperFigure] = Field(default_factory=list)
    created_at: str
    updated_at: str


def paper_from_row(row: Any) -> PaperItem:
    from on1y.utils.json_util import loads_json_list, loads_meta

    keys = set(row.keys())
    authors = [
        PaperAuthor.model_validate(value)
        for value in loads_json_list(row["authors_json"] or "[]")
        if isinstance(value, (dict, str))
    ]
    tags = [
        str(value).strip()
        for value in loads_json_list(row["tags_json"] or "[]")
        if str(value).strip()
    ]
    collections = [
        PaperCollection.model_validate(value)
        for value in (
            loads_json_list(row["zotero_collections_json"] or "[]")
            if "zotero_collections_json" in keys
            else []
        )
        if isinstance(value, dict)
    ]
    summary_value = loads_meta(row["ai_summary_json"]) if "ai_summary_json" in keys else {}
    figures = [
        PaperFigure.model_validate(value)
        for value in (
            loads_json_list(row["figures_json"] or "[]") if "figures_json" in keys else []
        )
        if isinstance(value, dict)
    ]
    return PaperItem(
        id=int(row["id"]),
        raw_id=int(row["raw_id"]) if row["raw_id"] is not None else None,
        title=str(row["title"]),
        authors=authors,
        abstract=str(row["abstract"]) if row["abstract"] else None,
        status=row["status"],
        year=int(row["year"]) if row["year"] is not None else None,
        venue=str(row["venue"]) if row["venue"] else None,
        doi=str(row["doi"]) if row["doi"] else None,
        url=str(row["url"]) if row["url"] else None,
        pdf_path=str(row["pdf_path"]) if row["pdf_path"] else None,
        zotero_key=str(row["zotero_key"]) if row["zotero_key"] else None,
        zotero_library_id=str(row["zotero_library_id"]) if row["zotero_library_id"] else None,
        zotero_attachment_key=(
            str(row["zotero_attachment_key"]) if row["zotero_attachment_key"] else None
        ),
        zotero_library_type=(
            str(row["zotero_library_type"]) if row["zotero_library_type"] else None
        ),
        zotero_version=int(row["zotero_version"]) if row["zotero_version"] is not None else None,
        zotero_collections=collections,
        citation_count=int(row["citation_count"]) if row["citation_count"] is not None else None,
        user_note_html=str(row["user_note_html"]) if row["user_note_html"] else None,
        importance=int(row["importance"]) if row["importance"] is not None else None,
        theme_slug=str(row["theme_slug"]) if row["theme_slug"] else None,
        tags=tags,
        ai_summary=PaperAiSummary.model_validate(summary_value) if summary_value else None,
        ai_summary_status=(
            str(row["ai_summary_status"]) if "ai_summary_status" in keys else "idle"
        ),
        ai_summary_error=(
            str(row["ai_summary_error"])
            if "ai_summary_error" in keys and row["ai_summary_error"]
            else None
        ),
        ai_summary_model=(
            str(row["ai_summary_model"])
            if "ai_summary_model" in keys and row["ai_summary_model"]
            else None
        ),
        ai_summary_updated_at=(
            str(row["ai_summary_updated_at"])
            if "ai_summary_updated_at" in keys and row["ai_summary_updated_at"]
            else None
        ),
        figures=figures,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def paper_dump(item: PaperItem) -> dict[str, Any]:
    payload = item.model_dump()
    payload["authors"] = [
        {**author.model_dump(), "google_scholar_url": author.google_scholar_url}
        for author in item.authors
    ]
    payload["google_scholar_url"] = "https://scholar.google.com/scholar?q=" + quote_plus(item.title)
    payload["zotero_reader_url"] = None
    if item.zotero_attachment_key:
        if item.zotero_library_type == "groups" and item.zotero_library_id:
            payload["zotero_reader_url"] = (
                f"zotero://open-pdf/groups/{item.zotero_library_id}/items/"
                f"{item.zotero_attachment_key}"
            )
        else:
            payload["zotero_reader_url"] = (
                "zotero://open-pdf/library/items/" + item.zotero_attachment_key
            )
    return payload