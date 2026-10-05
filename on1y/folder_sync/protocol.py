"""Immutable per-record operations; field parents retain concurrent versions."""

from __future__ import annotations

import unicodedata
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
_WINDOWS_INVALID = frozenset('<>:"\\|?*')
_WINDOWS_RESERVED = {
    "CON",
    "CONIN$",
    "CONOUT$",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
    *(f"COM{number}" for number in "¹²³"),
    *(f"LPT{number}" for number in "¹²³"),
}
_MAX_BLOB_BYTES = 2 * 1024**3
_MAX_PATH_BYTES = 4096
_MAX_COMPONENT_BYTES = 255


def portable_relative_path(value: str) -> str:
    """Return one NFC/POSIX relative path that is safe on Windows and macOS."""
    if not isinstance(value, str):
        raise ValueError("Literature path must be text")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized.startswith("/") or normalized.endswith("/"):
        raise ValueError("Literature path must be relative")
    if "\\" in normalized or len(normalized.encode("utf-8")) > _MAX_PATH_BYTES:
        raise ValueError("Literature path is not portable")
    parts = normalized.split("/")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or part.endswith((" ", "."))
            or len(part.encode("utf-8")) > _MAX_COMPONENT_BYTES
            or any(ord(char) < 32 or ord(char) == 127 or char in _WINDOWS_INVALID for char in part)
        ):
            raise ValueError("Literature path is not portable")
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise ValueError("Literature path uses a reserved name")
    return normalized


def canonical_relative_path(value: str) -> str:
    """Return the cross-platform, case-insensitive identity for a relative path."""
    return "/".join(part.casefold() for part in portable_relative_path(value).split("/"))


class BlobRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0, le=_MAX_BLOB_BYTES)


class Attachment(BlobRef):
    extension: str

    @model_validator(mode="after")
    def check_extension(self):
        if self.extension not in EXTENSIONS:
            raise ValueError("unsupported attachment format")
        return self


class LiteratureFileVersion(BaseModel):
    """A complete file version; tombstones retain the blob to expose delete/edit conflicts."""

    model_config = ConfigDict(extra="forbid")
    path: str
    blob: BlobRef
    deleted: bool = False

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return portable_relative_path(value)


class LiteratureSeed(BaseModel):
    """Immutable barrier proving one creator's initial tree snapshot is complete."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = VERSION
    library_id: UUID
    device_id: UUID
    event_ids: list[UUID] = Field(min_length=1, max_length=100_000)
    objects: list[BlobRef] = Field(default_factory=list, max_length=100_000)

    @model_validator(mode="after")
    def check_unique_entries(self):
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("duplicate Literature seed event")
        hashes = [item.sha256 for item in self.objects]
        if len(set(hashes)) != len(hashes):
            raise ValueError("duplicate Literature seed object")
        return self


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = VERSION
    library_id: UUID
    id: UUID
    device_id: UUID
    clock: int = Field(ge=1, le=2**63 - 1)
    kind: Literal["item", "theme", "book", "paper", "literature_file"]
    identity: str = Field(min_length=1, max_length=4096)
    patch: dict[str, Any] = Field(min_length=1, max_length=2048)
    parents: dict[str, list[UUID]]
    dependencies: list[UUID] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def check_fields(self):
        if set(self.parents) != set(self.patch):
            raise ValueError("each changed field needs its parent versions")
        if self.kind == "literature_file":
            if set(self.patch) != {"file"}:
                raise ValueError("Literature file events must replace the complete file version")
            version = LiteratureFileVersion.model_validate(self.patch["file"])
            if self.identity != canonical_relative_path(version.path):
                raise ValueError("Literature file identity does not match its path")
            self.patch["file"] = version.model_dump(mode="json")
            return self
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
