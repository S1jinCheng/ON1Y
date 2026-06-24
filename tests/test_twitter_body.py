"""Tests for X/Twitter Markdown body formatting."""

from __future__ import annotations

from on1y.extract.twitter_body import format_twitter_status_markdown, twitter_title_from_payload


def _main(**kwargs: object) -> dict:
    base = {
        "author": "",
        "handle": "",
        "text": "",
        "url": "",
        "images": [],
        "videos": [],
    }
    base.update(kwargs)
    return base


def test_format_simple_tweet_with_video_caption() -> None:
    body = format_twitter_status_markdown(
        {
            "kind": "tweet",
            "url": "https://x.com/alice/status/1",
            "main": _main(
                author="Alice",
                handle="alice",
                text="Hello #world",
                url="https://x.com/alice/status/1",
                images=[{"type": "image", "url": "https://pbs.twimg.com/media/a.jpg"}],
                videos=[
                    {
                        "type": "video",
                        "url": "https://x.com/alice/status/1/video/1",
                        "caption": "spoken line one",
                    }
                ],
            ),
        }
    )
    assert "## 主推文" in body
    assert "**Alice** (@alice)" in body
    assert "Hello #world" in body
    assert "![图片](https://pbs.twimg.com/media/a.jpg)" in body
    assert "[视频](https://x.com/alice/status/1/video/1)" in body
    assert "字幕：spoken line one" in body
    assert "[查看原帖]" in body


def test_format_quote_tweet_hierarchy() -> None:
    body = format_twitter_status_markdown(
        {
            "kind": "quote",
            "url": "https://x.com/bob/status/9",
            "main": _main(
                author="Bob",
                handle="bob",
                text="Agree with this take.",
            ),
            "embedded": _main(
                author="Carol",
                handle="carol",
                text="Original insight with full text.",
                url="https://x.com/carol/status/8",
            ),
        }
    )
    assert "## 主推文" in body
    assert "Agree with this take." in body
    assert "---" in body
    assert "## 转发" in body
    assert "[推文链接](https://x.com/carol/status/8)" in body
    assert "**Carol** (@carol)" in body
    assert "Original insight with full text." in body
    main_pos = body.index("## 主推文")
    forward_pos = body.index("## 转发")
    assert main_pos < forward_pos


def test_format_retweet_shows_reposter_then_embedded() -> None:
    body = format_twitter_status_markdown(
        {
            "kind": "retweet",
            "url": "https://x.com/eve/status/2",
            "main": _main(reposter="Eve"),
            "embedded": _main(
                author="Dave",
                handle="dave",
                text="Worth reading.",
                url="https://x.com/dave/status/3",
                videos=[
                    {
                        "type": "video",
                        "url": "https://x.com/dave/status/3/video/1",
                        "caption": "clip transcript",
                    }
                ],
            ),
        }
    )
    assert "## 主推文" in body
    assert "*Eve 转推*" in body
    assert "## 转发" in body
    assert "**Dave** (@dave)" in body
    assert "Worth reading." in body
    assert "字幕：clip transcript" in body


def test_format_image_only_tweet() -> None:
    body = format_twitter_status_markdown(
        {
            "kind": "tweet",
            "url": "https://x.com/alice/status/2",
            "main": {
                "author": "Alice",
                "handle": "alice",
                "text": "",
                "images": [{"type": "image", "url": "https://pbs.twimg.com/media/p.jpg"}],
                "videos": [],
            },
        }
    )
    assert "## 主推文" in body
    assert "![图片]" in body


def test_payload_has_content() -> None:
    from on1y.extract.twitter_body import payload_has_content

    assert payload_has_content({"main": {"text": "", "images": [{"url": "x"}]}})
    assert not payload_has_content({"main": {"text": "", "images": [], "videos": []}})


def test_parse_twitter_author_from_markdown_retweet() -> None:
    from on1y.extract.twitter_body import parse_twitter_author_from_markdown

    body = """## 主推文

*Eve 转推*

## 转发

**Dave** (@dave)

Worth reading.
"""
    parsed = parse_twitter_author_from_markdown(body)
    assert parsed == {"author": "Dave", "handle": "dave"}
    title = twitter_title_from_payload(
        {
            "main": _main(author="Z", handle="z", text="Short post"),
        }
    )
    assert title == "Z: Short post"
