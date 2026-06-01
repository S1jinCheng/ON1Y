"""Tests for bilingual subtitle parsing."""

from pathlib import Path

from on1y.extract.subtitles import (
    build_video_body,
    collect_bilingual_subtitles,
    detect_lang_group,
    is_substantive_subtitle,
    lang_code_from_path,
    pick_best_per_group,
    strip_subtitle_markup,
)


def test_detect_lang_group() -> None:
    assert detect_lang_group("zh-Hans") == "zh"
    assert detect_lang_group("zh-CN") == "zh"
    assert detect_lang_group("en-US") == "en"
    assert detect_lang_group("ai-zh") == "zh"
    assert detect_lang_group("ai-en") == "en"


def test_lang_code_from_path() -> None:
    assert lang_code_from_path(Path("abc.zh-Hans.vtt")) == "zh-Hans"
    assert lang_code_from_path(Path("abc.zh-CN.vtt")) == "zh-CN"
    assert lang_code_from_path(Path("abc.en.vtt")) == "en"


def test_pick_best_per_group() -> None:
    files = [
        Path("v.en.vtt"),
        Path("v.zh-Hans.vtt"),
        Path("v.zh.vtt"),
    ]
    chosen = pick_best_per_group(files)
    assert "zh" in chosen
    assert "en" in chosen
    assert chosen["zh"].name == "v.zh-Hans.vtt"


def test_collect_bilingual_subtitles_prefers_zh(tmp_path: Path) -> None:
    (tmp_path / "id.zh-Hans.vtt").write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\n你好世界\n",
        encoding="utf-8",
    )
    (tmp_path / "id.en.vtt").write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello world\n",
        encoding="utf-8",
    )
    text, found = collect_bilingual_subtitles(
        tmp_path,
        lang_config="zh-Hans,en",
        prefer_lang="zh",
    )
    assert found == ["zh"]
    assert "你好世界" in text
    assert "Hello world" not in text
    assert "字幕（中文）" in text


def test_collect_bilingual_subtitles_prefers_en(tmp_path: Path) -> None:
    (tmp_path / "id.zh-Hans.vtt").write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\n你好世界\n",
        encoding="utf-8",
    )
    (tmp_path / "id.en.vtt").write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello world\n",
        encoding="utf-8",
    )
    text, found = collect_bilingual_subtitles(
        tmp_path,
        lang_config="zh-Hans,en",
        prefer_lang="en",
    )
    assert found == ["en"]
    assert "Hello world" in text
    assert "你好世界" not in text


def test_strip_subtitle_markup() -> None:
    raw = (
        "WEBVTT\n\n"
        "Kind: captions\n"
        "Language: en\n"
        "Everybody<00:00:00.640><c> is</c><00:00:00.800><c> fine</c>\n"
        "Everybody is fine\n"
        "Everybody is fine\n"
    )
    cleaned = strip_subtitle_markup(raw)
    assert "<00:00:" not in cleaned
    assert "Kind:" not in cleaned
    assert "Everybody is fine" in cleaned
    assert cleaned.count("Everybody is fine") == 1


def test_strip_subtitle_markup_srt_inline() -> None:
    raw = (
        "00:00:00,140 --> 00:00:01,280 在PPT制作中 "
        "00:00:01,280 --> 00:00:03,140 想要精准地体现地理位置\n"
        "00:00:03,140 --> 00:00:04,800 就需要用到地图素材\n"
    )
    cleaned = strip_subtitle_markup(raw)
    assert "-->" not in cleaned
    assert "00:00:00" not in cleaned
    assert "在PPT制作中" in cleaned
    assert "就需要用到地图素材" in cleaned


def test_build_video_body_zh_only_is_ok() -> None:
    body, partial = build_video_body(
        title="测试",
        subtitle_text="## 字幕（中文）\n\n你好，这是足够长的中文字幕内容用于测试。",
        description=None,
        langs_found=["zh"],
        prefer_lang="zh",
    )
    assert partial is None
    assert "你好" in body


def test_is_substantive_subtitle_rejects_timestamp_only() -> None:
    assert not is_substantive_subtitle("00:00:00,826 --> 00:00:05,826")
    assert is_substantive_subtitle("这是一段足够长的字幕正文内容测试。")
