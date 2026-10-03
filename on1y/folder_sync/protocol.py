"""Immutable per-record operations; field parents retain concurrent versions."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from on1y.device_sync.protocol import Operation

VERSION = 1
MAX_EVENT_BYTES = 16 * 1024 * 1024
BOOK_FIELDS = {
    "title",
    "author",
    "translator",
    "publisher",
    "cover_url",
    "summary",
    "status",
    "links_json",
    "notes",
    "created_at",
}
PAPER_FIELDS = {
    "title",
    "authors_json",
    "abstract",
    "status",
    "year",
    "venue",
    "doi",
    "url",
    "citation_count",
    "created_at",
    "ai_summary_json",
    "ai_summary_model",
    "ai_summary_updated_at",
    "zotero_collections_json",
    "literature_paper_id",
}
EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw", ".azw3", ".txt", ".djvu"}


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extension: str
    size: int = Field(ge=0, le=2 * 1024**3)

    @model_validator(mode="after")
    def check_extension(self):
        if self.extension not in EXTENSIONS:
            raise ValueError("unsupported attachment format")
        return self


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = VERSION
    library_id: UUID
    id: UUID
    device_id: UUID
    clock: int = Field(ge=1, le=2**63 - 1)
    kind: Literal["item", "theme", "book", "paper"]
    identity: str = Field(min_length=1, max_length=4096)
    patch: dict[str, Any] = Field(min_length=1, max_length=2048)
    parents: dict[str, list[UUID]]
    dependencies: list[UUID] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def check_fields(self):
        if set(self.parents) != set(self.patch):
            raise ValueError("each changed field needs its parent versions")
        shared = {}
        for field, value in self.patch.items():
            if field == "attachment" and self.kind in {"book", "paper"}:
                if value is not None:
                    Attachment.model_validate(value)
            elif field.startswith("library/") and self.kind in {"book", "paper"}:
                name = field[8:]
                allowed = BOOK_FIELDS if self.kind == "book" else PAPER_FIELDS
                if name not in allowed:
                    raise ValueError("unsupported library field")
                if name in {"year", "citation_count"}:
                    if value is not None and (type(value) is not int or value < 0):
                        raise ValueError("invalid library number")
                elif value is not None and not isinstance(value, str):
                    raise ValueError("invalid library text")
                if name == "status" and value not in (
                    {"reading", "read"}
                    if self.kind == "book"
                    else {"to_read", "reading", "read", "dismissed"}
                ):
                    raise ValueError("invalid reading status")
                if name.endswith("_json") and value is not None:
                    import json

                    from on1y.books.models import BookLink
                    from on1y.papers.models import PaperAiSummary, PaperAuthor, PaperCollection

                    data = json.loads(value)
                    if name == "ai_summary_json":
                        PaperAiSummary.model_validate(data)
                    else:
                        if not isinstance(data, list):
                            raise ValueError("invalid library list")
                        model = {
                            "links_json": BookLink,
                            "authors_json": PaperAuthor,
                            "zotero_collections_json": PaperCollection,
                        }[name]
                        for entry in data:
                            model.model_validate(entry)
            else:
                shared[field] = value
        if shared:
            Operation(
                op_id=str(self.id),
                device_id=str(self.device_id),
                kind="theme" if self.kind == "theme" else "item",
                identity=self.identity,
                patch=shared,
                base={field: 0 for field in shared},
            )
        return self
