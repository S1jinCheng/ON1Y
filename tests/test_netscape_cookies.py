"""Netscape cookie conversion for yt-dlp."""

from pathlib import Path

from on1y.cookies.netscape import write_netscape_cookie_file


def test_write_netscape(tmp_path: Path) -> None:
    cookies = [
        {
            "name": "SESSDATA",
            "value": "abc123",
            "domain": ".bilibili.com",
            "path": "/",
            "secure": True,
            "expires": 1893456000,
        }
    ]
    out = tmp_path / "bilibili.json.netscape.txt"
    write_netscape_cookie_file(cookies, out)
    text = out.read_text(encoding="utf-8")
    assert "Netscape HTTP Cookie File" in text
    assert "SESSDATA" in text
    assert ".bilibili.com" in text
