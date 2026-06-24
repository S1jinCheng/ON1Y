"""Format X/Twitter status pages as hierarchical Markdown (mirrors X layout)."""

from __future__ import annotations

import re
from typing import Any

_AUTHOR_MD_RE = re.compile(r"\*\*(.+?)\*\* \(@(\w+)\)")


def _author_line(author: str, handle: str) -> str:
    author = author.strip()
    handle = handle.strip().removeprefix("@")
    if author and handle:
        return f"**{author}** (@{handle})"
    if author:
        return f"**{author}**"
    if handle:
        return f"@{handle}"
    return ""


def _format_images(images: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for item in images:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        lines.append(f"![图片]({url})")
    return lines


def _format_videos(videos: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for item in videos:
        url = str(item.get("url") or "").strip()
        caption = str(item.get("caption") or "").strip()
        key = url or caption
        if not key or key in seen:
            continue
        seen.add(key)
        if url:
            lines.append(f"[视频]({url})")
        else:
            lines.append("[视频]")
        if caption:
            lines.append("")
            lines.append(f"字幕：{caption}")
    return lines


def _format_tweet_section(block: dict[str, Any], *, heading: str | None = None) -> list[str]:
    """Author, text, images, then each video with caption (X-like order)."""
    lines: list[str] = []
    if heading:
        lines.append(heading)
        lines.append("")

    author = _author_line(
        str(block.get("author") or ""),
        str(block.get("handle") or ""),
    )
    text = str(block.get("text") or "").strip()
    reposter = str(block.get("reposter") or "").strip()

    if reposter:
        lines.append(f"*{reposter} 转推*")
        lines.append("")

    if author:
        lines.append(author)
        lines.append("")

    if text:
        lines.append(text)

    images = _format_images(list(block.get("images") or []))
    if images:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(images)

    videos = list(block.get("videos") or [])
    for idx, video in enumerate(videos):
        if not isinstance(video, dict):
            continue
        vlines = _format_videos([video])
        if not vlines:
            continue
        lines.append("")
        if len(videos) > 1:
            lines.append(f"### 视频 {idx + 1}")
            lines.append("")
        lines.extend(vlines)

    return lines


def _section_divider() -> list[str]:
    return ["", "---", ""]


def format_twitter_status_markdown(data: dict[str, Any]) -> str:
    """
  Layout (top → bottom, like X):

  ## 主推文 — author, comment text, main images/videos
  ---
  ## 转发 — link, quoted/retweeted author, text, media
  """
    lines: list[str] = []

    main = data.get("main") if isinstance(data.get("main"), dict) else {}
    embedded = data.get("embedded") if isinstance(data.get("embedded"), dict) else None
    kind = str(data.get("kind") or "tweet")

    # Legacy flat payload → nested blocks
    if not main and data.get("author") is not None:
        main = {
            "author": data.get("author"),
            "handle": data.get("handle"),
            "text": data.get("text"),
            "url": data.get("url"),
            "images": [m for m in (data.get("media") or []) if m.get("type") == "image"],
            "videos": [m for m in (data.get("media") or []) if m.get("type") == "video"],
        }
        if kind == "quote" and isinstance(data.get("quoted"), dict):
            q = data["quoted"]
            embedded = {
                "author": q.get("author"),
                "handle": q.get("handle"),
                "text": q.get("text"),
                "url": q.get("url"),
                "images": [m for m in (q.get("media") or []) if m.get("type") == "image"],
                "videos": [m for m in (q.get("media") or []) if m.get("type") == "video"],
            }
        elif kind == "retweet" or data.get("is_retweet"):
            embedded = {
                "author": main.get("author"),
                "handle": main.get("handle"),
                "text": main.get("text"),
                "url": main.get("url"),
                "images": main.get("images"),
                "videos": main.get("videos"),
            }
            main = {
                "reposter": _reposter_from_social(data.get("social_context")),
                "text": "",
                "images": [],
                "videos": [],
            }

    lines.extend(_format_tweet_section(main, heading="## 主推文"))

    if embedded:
        lines.extend(_section_divider())
        lines.append("## 转发")
        lines.append("")
        embed_url = str(embedded.get("url") or "").strip()
        if embed_url:
            lines.append(f"[推文链接]({embed_url})")
            lines.append("")
        block_lines = _format_tweet_section(embedded, heading=None)
        if block_lines:
            lines.extend(block_lines)

    post_url = str(data.get("url") or main.get("url") or "").strip()
    if post_url:
        lines.append("")
        lines.append(f"[查看原帖]({post_url})")

    return "\n".join(lines).strip()


def _reposter_from_social(social: Any) -> str:
    text = str(social or "").strip()
    if not text:
        return ""
    for suffix in (" reposted", " retweeted", " 转推", " 转发了", " Reposted", " Retweeted"):
        if suffix.strip() in text or text.endswith(suffix.strip()):
            return text.replace(suffix, "").strip()
    return text


def twitter_title_from_payload(data: dict[str, Any]) -> str | None:
    """Short display title for feeds."""
    main = data.get("main") if isinstance(data.get("main"), dict) else data
    embedded = data.get("embedded") if isinstance(data.get("embedded"), dict) else None
    author = str(main.get("author") or "").strip()
    handle = str(main.get("handle") or "").strip().removeprefix("@")
    text = str(main.get("text") or "").strip()
    if not text and embedded:
        text = str(embedded.get("text") or "").strip()
    if not text and isinstance(data.get("quoted"), dict):
        text = str(data["quoted"].get("text") or "").strip()
    if not author and embedded:
        author = str(embedded.get("author") or "").strip()
    preview = text.replace("\n", " ")[:80]
    if author and preview:
        return f"{author}: {preview}"
    if handle and preview:
        return f"@{handle}: {preview}"
    return author or (f"@{handle}" if handle else None)


def _block_has_content(block: dict[str, Any] | None) -> bool:
    if not isinstance(block, dict):
        return False
    if str(block.get("text") or "").strip():
        return True
    if block.get("images") or block.get("videos") or block.get("media"):
        return True
    return False


def payload_has_content(data: dict[str, Any]) -> bool:
    """True when extracted payload has tweet text or attachment metadata."""
    if _block_has_content(data.get("main") if isinstance(data.get("main"), dict) else None):
        return True
    if _block_has_content(data.get("embedded") if isinstance(data.get("embedded"), dict) else None):
        return True
    quoted = data.get("quoted")
    if isinstance(quoted, dict) and _block_has_content(quoted):
        return True
    if str(data.get("text") or "").strip():
        return True
    return bool(data.get("media"))


def parse_twitter_author_from_markdown(body: str) -> dict[str, str]:
    """Read author + handle from stored Markdown (retweets use ## 转发 block)."""
    text = str(body or "")
    if not text.strip():
        return {}
    forward_idx = text.find("## 转发")
    if forward_idx >= 0:
        chunk = text[forward_idx:]
    else:
        main_idx = text.find("## 主推文")
        chunk = text[main_idx:] if main_idx >= 0 else text
    match = _AUTHOR_MD_RE.search(chunk)
    if not match:
        return {}
    author = match.group(1).strip()
    handle = match.group(2).strip()
    if not author and not handle:
        return {}
    return {"author": author, "handle": handle}
