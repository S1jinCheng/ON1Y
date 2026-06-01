"""Tests for original text cleanup."""

from on1y.utils.text_format import format_original_text, format_video_body_text


def test_format_original_text_strips_vtt_tags() -> None:
    raw = """好的<00:00:06.182><c>的</c><00:00:06.444><c>，</c>
好的，欢迎各位。
好的，欢迎各位。
今天<00:00:08.159><c>莅临</c>。"""
    out = format_original_text(raw)
    assert "<00:00:" not in out
    assert "<c>" not in out
    assert "欢迎各位" in out
    assert out.count("欢迎各位") == 1


def test_format_video_body_text_strips_bilibili_srt() -> None:
    raw = """# 测试视频

## 字幕（中文）


00:00:00,140 --> 00:00:01,280 在PPT制作中 00:00:01,280 --> 00:00:03,140 想要精准地体现地理位置
00:00:03,140 --> 00:00:04,800 就需要用到地图素材
"""
    out = format_video_body_text(raw)
    assert out is not None
    assert "-->" not in out
    assert "在PPT制作中" in out
    assert "就需要用到地图素材" in out
    assert "## 字幕" in out
