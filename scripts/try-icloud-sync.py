"""Exercise a selected cloud folder with synthetic data and two local databases.

This checks local cloud-folder I/O and replication logic, not Apple's delivery
to another physical computer. It never opens the user's production database.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    args = parser.parse_args()
    local = args.local.resolve()
    if (local / "device-a/on1y.db").exists():
        raise SystemExit("Use a new local test directory; existing trial data is preserved.")
    local.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "ON1Y_DISABLE_DOTENV": "1",
            "ON1Y_DATA_DIR": str(local / "device-a"),
            "ON1Y_DB_PATH": str(local / "device-a/on1y.db"),
            "ON1Y_BOOTSTRAP_PASSWORD": "isolated-icloud-test-password",
        }
    )
    import pymupdf
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.books.models import BookLink, BookShelfCreate
    from on1y.books.shelf import create_shelf_item, list_shelf_items
    from on1y.folder_sync.engine import FolderSync
    from on1y.papers.models import PaperCreate, PaperUpdate
    from on1y.papers.shelf import create_paper, list_papers, update_paper

    pdf = local / "On1y Sync Sample.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "On1y iCloud sync test", fontsize=22)
        page.insert_text((72, 115), "Synthetic sample only. No personal library data.")
        document.save(pdf)
    epub = local / "On1y Sync Sample.epub"
    with ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
</rootfiles></container>""",
            compress_type=ZIP_DEFLATED,
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">on1y-sync-sample</dc:identifier>
<dc:title>On1y Sync Sample</dc:title><dc:language>en</dc:language>
<meta property="dcterms:modified">2026-10-01T00:00:00Z</meta></metadata>
<manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>
<spine><itemref idref="chapter"/></spine></package>""",
        )
        archive.writestr(
            "chapter.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>On1y Sync Sample</title></head><body><h1>On1y iCloud sync test</h1>
<p>Synthetic sample only. No personal library data.</p></body></html>""",
        )
        archive.writestr(
            "nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"
xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head>
<body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">Sample</a></li></ol></nav>
</body></html>""",
        )
    stores = []
    try:
        for device in ("device-a", "device-b"):
            directory = local / device
            directory.mkdir()
            store = SqliteStorage(directory / "on1y.db")
            store.initialize()
            stores.append(store)
        a, b = [FolderSync(store) for store in stores]
        a.configure(1, str(args.folder.resolve()), True, create=True)
        b.configure(1, str(args.folder.resolve()), True)
        create_shelf_item(
            a.storage,
            1,
            BookShelfCreate(
                title="iCloud 测试电子书",
                author="On1y",
                links=[BookLink(label="Sample", url=epub.as_uri())],
                notes="仅用于测试，不含个人资料。\ncached: " + str(epub),
                tags=["iCloud 测试"],
            ),
        )
        create_paper(
            a.storage,
            1,
            PaperCreate(
                title="iCloud 测试论文",
                authors=["On1y"],
                pdf_path=str(pdf),
                tags=["iCloud 测试"],
            ),
        )
        a.sync(1)
        b.sync(1)
        received = list_papers(b.storage, 1)[0]
        update_paper(
            b.storage,
            1,
            received.id,
            PaperUpdate(
                user_note_html="<p>来自第二个测试资料库的笔记，双向同步成功。</p>",
                status="read",
            ),
        )
        b.sync(1)
        a.sync(1)
        b.sync(1)
        result = list_papers(a.storage, 1)[0]
        assert result.user_note_html == "<p>来自第二个测试资料库的笔记，双向同步成功。</p>"
        assert result.status == "read"
        assert Path(result.pdf_path).read_bytes() == pdf.read_bytes()
        assert Path(list_shelf_items(b.storage, 1)[0].local_path).read_bytes() == epub.read_bytes()
        report = {
            "cloud_folder": str(args.folder.resolve()),
            "local_trial": str(local),
            "library_id": a.config()["library_id"],
            "books": 1,
            "papers": 1,
            "attachment_bytes_verified": True,
            "bidirectional_note_verified": True,
            "cloud_delivery_to_windows_verified": False,
        }
        (local / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        for store in stores:
            store.close()


if __name__ == "__main__":
    main()
