"""Plain text from simple HTML notes."""

from __future__ import annotations

import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")


def html_to_plain_text(html: str | None) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub(" ", str(html))
    return unescape(re.sub(r"\s+", " ", text)).strip()
