"""Tests for zero-LLM tag extraction."""

from __future__ import annotations

from on1y.tags.extract import (
    collect_short_content_tags,
    extract_cashtags,
    extract_hashtags,
    extract_meta_tags,
)


def test_extract_hashtags() -> None:
    body = "讨论 #AI 和 #大模型 的趋势"
    assert extract_hashtags(body) == ["AI", "大模型"]


def test_extract_cashtags() -> None:
    assert extract_cashtags("看好 $TSLA 和 $NVDA") == ["TSLA", "NVDA"]


def test_extract_meta_tags_twitter() -> None:
    tags = extract_meta_tags(
        platform="twitter",
        source_meta={"feed_label": "x-home", "author": "Alice"},
        author="Alice",
    )
    assert "X" in tags
    assert "X关注" in tags
    assert "Alice" in tags


def test_collect_short_content_tags_merges_sources() -> None:
    body = "分享 #Rust 教程 https://github.com/rust-lang/rust"
    tags = collect_short_content_tags(
        body=body,
        platform="twitter",
        url="https://x.com/i/web/status/1",
        source_meta={"feed_label": "x-bookmarks", "author": "Bob"},
    )
    assert "Rust" in tags
    assert "github.com" in tags
    assert "X书签" in tags
    assert "Bob" in tags
