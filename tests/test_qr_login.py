"""Tests for cookie QR login."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.cookies.qr_login.bilibili import poll_bilibili_qr
from on1y.cookies.qr_login.service import poll_qr_login, start_qr_login


def test_poll_bilibili_qr_pending() -> None:
    holder = MagicMock()
    holder.client.get.return_value.json.return_value = {
        "code": 0,
        "data": {"code": 86101},
    }
    holder.client.get.return_value.raise_for_status = MagicMock()
    assert poll_bilibili_qr(holder) == ("pending", None)


def test_poll_bilibili_qr_success() -> None:
    holder = MagicMock()
    holder.client.get.return_value.json.return_value = {
        "code": 0,
        "data": {"code": 0},
    }
    holder.client.get.return_value.raise_for_status = MagicMock()
    assert poll_bilibili_qr(holder) == ("success", None)


@patch("on1y.cookies.qr_login.service.start_bilibili_qr")
def test_start_qr_login_bilibili(mock_start: MagicMock) -> None:
    holder = MagicMock()
    holder.qr_url = "https://account.bilibili.com/scan"
    mock_start.return_value = holder
    view = start_qr_login("bilibili", user_id=1)
    assert view["platform"] == "bilibili"
    assert view["method"] == "app_scan"
    assert view["qr_content"] == holder.qr_url
    assert view["status"] == "pending"


@patch("on1y.cookies.qr_login.service.persist_user_cookie_payload")
@patch("on1y.cookies.qr_login.service.poll_bilibili_qr", return_value=("success", None))
@patch("on1y.cookies.qr_login.service.httpx_client_to_storage_state", return_value={"cookies": [], "origins": []})
@patch("on1y.cookies.qr_login.service.start_bilibili_qr")
def test_poll_qr_login_success_persists(
    mock_start: MagicMock,
    _state: MagicMock,
    _poll: MagicMock,
    persist: MagicMock,
) -> None:
    holder = MagicMock()
    holder.qr_url = "https://account.bilibili.com/scan"
    holder.client = MagicMock()
    mock_start.return_value = holder
    persist.return_value = {"platform": "bilibili", "count": 5, "account": {"ok": True}}
    started = start_qr_login("bilibili", user_id=1)
    result = poll_qr_login(started["session_id"], user_id=1)
    assert result["status"] == "success"
    assert result["import_result"]["count"] == 5
    persist.assert_called_once()
