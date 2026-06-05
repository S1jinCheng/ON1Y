"""Tests for author metadata merge helpers."""

from __future__ import annotations

from on1y.utils.author_meta import author_meta_patch, is_unreliable_avatar_url, merge_author_meta, pick_better_avatar, resolve_author_avatar


def test_is_unreliable_avatar_url() -> None:
    assert is_unreliable_avatar_url("")
    assert is_unreliable_avatar_url("https://unavatar.io/youtube/UCabc")
    assert not is_unreliable_avatar_url("https://i0.hdslb.com/bfs/face/x.jpg")


def test_pick_better_avatar_prefers_real_url() -> None:
    assert (
        pick_better_avatar(
            "https://unavatar.io/youtube/UCabc",
            "https://yt3.ggpht.com/abc=s88",
        )
        == "https://yt3.ggpht.com/abc=s88"
    )


def test_merge_author_meta_preserves_existing_avatar() -> None:
    base = {
        "author": "Alice",
        "author_avatar": "https://i0.hdslb.com/bfs/face/alice.jpg",
        "cover_image": "https://example.com/cover.jpg",
    }
    patch = author_meta_patch(
        author="Bob",
        author_avatar=None,
        cover_image="https://example.com/new-cover.jpg",
    )
    merged = merge_author_meta(base, patch)
    assert merged["author"] == "Alice"
    assert merged["author_avatar"] == "https://i0.hdslb.com/bfs/face/alice.jpg"
    assert merged["cover_image"] == "https://example.com/cover.jpg"


def test_merge_author_meta_fills_missing_avatar() -> None:
    base = {"author": "Alice", "author_url": "https://space.bilibili.com/1"}
    patch = author_meta_patch(
        author_avatar="https://i0.hdslb.com/bfs/face/alice.jpg",
        cover_image="https://example.com/cover.jpg",
    )
    merged = merge_author_meta(base, patch)
    assert resolve_author_avatar(merged) == "https://i0.hdslb.com/bfs/face/alice.jpg"
    assert merged["cover_image"] == "https://example.com/cover.jpg"
