from on1y.books.kindle_notes import merge_kindle_status, parse_kindle_status


def test_merge_and_parse_kindle_status():
    notes = "cached: /tmp/book.epub\nsource: zlib"
    merged = merge_kindle_status(notes, "sent")
    assert parse_kindle_status(merged) == "sent"
    assert "cached: /tmp/book.epub" in merged

    updated = merge_kindle_status(merged, "skipped", "未配置邮箱")
    assert parse_kindle_status(updated) == "skipped"
    assert "kindle_detail: 未配置邮箱" in updated
    assert updated.count("kindle_status:") == 1
