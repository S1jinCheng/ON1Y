"""Basic integrity checks for downloaded ebooks."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import BinaryIO

_MIN_EBOOK_BYTES = 1024


def _valid_epub(stream: BinaryIO) -> bool:
    try:
        with zipfile.ZipFile(stream) as archive:
            info = archive.getinfo("mimetype")
            if info.compress_type != zipfile.ZIP_STORED:
                return False
            if archive.read(info) != b"application/epub+zip":
                return False
            names = set(archive.namelist())
            return "META-INF/container.xml" in names and any(
                name.lower().endswith(".opf")
                for name in names
            )
    except (KeyError, OSError, ValueError, zipfile.BadZipFile):
        return False


def _validate(data: bytes | None, path: Path | None, fmt: str) -> tuple[bool, str, int]:
    size = path.stat().st_size if path is not None else len(data or b"")
    if size < _MIN_EBOOK_BYTES:
        return False, "文件过小，可能下载不完整", size

    fmt_l = fmt.lower()
    if fmt_l == "pdf":
        if path is not None:
            with path.open("rb") as stream:
                ok = stream.read(5) == b"%PDF-"
        else:
            ok = (data or b"").startswith(b"%PDF-")
        return ok, "PDF 文件头有效" if ok else "不是有效的 PDF 文件", size

    if fmt_l == "epub":
        stream: BinaryIO = path.open("rb") if path is not None else io.BytesIO(data or b"")
        try:
            ok = _valid_epub(stream)
        finally:
            stream.close()
        return ok, "EPUB 结构正常" if ok else "EPUB 结构损坏或不完整", size

    if fmt_l == "mobi":
        if path is not None:
            with path.open("rb") as stream:
                stream.seek(60)
                marker = stream.read(8)
        else:
            marker = (data or b"")[60:68]
        ok = marker == b"BOOKMOBI"
        return ok, "MOBI 文件头有效" if ok else "不是有效的 MOBI 文件", size

    return True, "未知格式，仅检查文件大小", size


def validate_ebook_bytes(data: bytes, fmt: str) -> dict[str, object]:
    ok, detail, size = _validate(data, None, fmt)
    return {"ok": ok, "size_bytes": size, "detail": detail}


def validate_ebook_file(path: Path, fmt: str) -> dict[str, object]:
    """Validate an ebook without loading the entire file into memory."""
    try:
        ok, detail, size = _validate(None, path, fmt)
    except OSError as exc:
        return {"ok": False, "size_bytes": 0, "detail": f"无法读取文件：{exc}"}
    return {"ok": ok, "size_bytes": size, "detail": detail}
