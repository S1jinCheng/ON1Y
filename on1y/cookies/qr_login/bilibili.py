"""Bilibili app QR login (official passport API)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

BILI_QR_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILI_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


@dataclass
class BilibiliQrHolder:
    client: httpx.Client
    qrcode_key: str
    qr_url: str

    def close(self) -> None:
        self.client.close()


def start_bilibili_qr() -> BilibiliQrHolder:
    client = httpx.Client(headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True)
    response = client.get(BILI_QR_GENERATE)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        client.close()
        raise RuntimeError(f"Bilibili QR generate failed: {payload.get('message')}")
    data = payload.get("data") or {}
    qrcode_key = str(data.get("qrcode_key") or "").strip()
    qr_url = str(data.get("url") or "").strip()
    if not qrcode_key or not qr_url:
        client.close()
        raise RuntimeError("Bilibili QR generate returned empty key/url")
    return BilibiliQrHolder(client=client, qrcode_key=qrcode_key, qr_url=qr_url)


def poll_bilibili_qr(holder: BilibiliQrHolder) -> tuple[str, str | None]:
    """
    Return (status, message).
    status: pending | scanned | success | expired | error
    """
    response = holder.client.get(BILI_QR_POLL, params={"qrcode_key": holder.qrcode_key})
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        return "error", str(payload.get("message") or "poll failed")
    data = payload.get("data") or {}
    poll_code = int(data.get("code") or 0)
    # 86101 not scanned; 86090 scanned not confirmed; 0 success; 86038 expired
    if poll_code == 86101:
        return "pending", None
    if poll_code == 86090:
        return "scanned", None
    if poll_code == 86038:
        return "expired", "QR code expired"
    if poll_code == 0:
        return "success", None
    return "pending", str(data.get("message") or None)
