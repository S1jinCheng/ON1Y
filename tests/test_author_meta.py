"""Tests for author metadata helpers."""

from on1y.utils.author_meta import author_fields_from_meta, author_meta_patch


def test_author_fields_from_meta() -> None:
    fields = author_fields_from_meta(
        {
            "uploader": "Channel X",
            "author_avatar": "https://example.com/avatar.jpg",
            "channel_url": "https://example.com/channel",
            "cover_image": "https://example.com/cover.jpg",
        }
    )
    assert fields["author"] == "Channel X"
    assert fields["author_avatar"] == "https://example.com/avatar.jpg"
    assert fields["author_url"] == "https://example.com/channel"
    assert fields["cover_image"] == "https://example.com/cover.jpg"


def test_author_meta_patch_skips_empty() -> None:
    assert author_meta_patch(author="Alice", author_avatar="") == {"author": "Alice"}


def test_rejects_video_thumbnail_as_avatar() -> None:
    fields = author_fields_from_meta(
        {
            "author_avatar": "https://i.ytimg.com/vi/abc123/hqdefault.jpg",
            "channel_id": "UCtest123",
        }
    )
    assert "ytimg.com/vi/" not in fields["author_avatar"]
    assert fields["author_avatar"] == "https://unavatar.io/youtube/UCtest123"
    assert fields["cover_image"] == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"


def test_channel_id_in_patch() -> None:
    patch = author_meta_patch(channel_id="UCabc")
    assert patch == {"channel_id": "UCabc"}
