"""Basic integrity checks for downloaded ebooks."""

from __future__ import annotations

import io
import zipfile


def validate_ebook_bytes(data: bytes, fmt: str) -> dict[str, object]:
    size = len(data)
    fmt_l = fmt.lower()
    ok = size >= 1024
    detail = ""

    if fmt_l == "pdf":
        ok = data.startswith(b"%PDF-")
        detail = "PDF 文件头有效" if ok else "不是有效的 PDF 文件"
    elif fmt_l == "epub":
        ok = zipfile.is_zipfile(io.BytesIO(data))
        if ok:
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    names = zf.namelist()
                    ok = any(n == "mimetype" for n in names) or bool(names)
            except zipfile.BadZipFile:
                ok = False
        detail = "EPUB 结构正常" if ok else "EPUB 压缩包损坏或不完整"
    elif fmt_l == "mobi":
        head = data[:8]
        ok = head.startswith(b"BOOKMOBI") or head[4:8] == b"MOBI"
        detail = "MOBI 文件头有效" if ok else "不是有效的 MOBI 文件"
    else:
        detail = "未知格式，仅检查文件大小"

    if size < 1024:
        ok = False
        detail = "文件过小，可能下载不完整"

    return {
        "ok": ok,
        "size_bytes": size,
        "detail": detail,
    }
