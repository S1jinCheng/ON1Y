"""Tests for transcript classification."""

from on1y.utils.transcript_meta import (
    body_has_dual_transcripts,
    classify_transcript,
    extract_transcript_plain,
    pick_single_transcript,
)


def test_classify_zh() -> None:
    body = "# Title\n\n## 字幕（中文）\n\n你好世界"
    assert classify_transcript(body) == "zh"


def test_classify_en() -> None:
    body = "# Title\n\n## Subtitle (English)\n\nHello world"
    assert classify_transcript(body) == "en"


def test_classify_none() -> None:
    body = "# Title\n\n## Description\n\nOnly marketing copy"
    assert classify_transcript(body) == "none"


def test_pick_single_transcript_from_dual_inline() -> None:
    body = (
        "# Title\n\n## 字幕（中文）\n\n你好世界 谢谢 ## Subtitle (English) Hello world thanks"
    )
    zh_only = pick_single_transcript(body, prefer_lang="zh")
    assert "## Subtitle" not in zh_only
    assert "你好世界" in zh_only
    assert "Hello world" not in zh_only


def test_body_has_dual_transcripts() -> None:
    body = "# T\n\n## 字幕（中文）\n\nx\n\n## Subtitle (English)\n\ny"
    assert body_has_dual_transcripts(body) is True


def test_extract_transcript_plain() -> None:
    body = "# Title\n\n## Subtitle (English)\n\nHello world"
    assert extract_transcript_plain(body) == "Hello world"
