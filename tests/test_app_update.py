"""Tests for GitHub release update checks."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from on1y.app_update import check_app_update, parse_version, version_less_than
from on1y.config import get_settings
from on1y.web.app import create_app


def test_parse_version_and_compare() -> None:
    assert parse_version("v0.1.0") == (0, 1, 0)
    assert parse_version("1.2.3") == (1, 2, 3)
    assert version_less_than("0.1.0", "0.2.0")
    assert not version_less_than("0.2.0", "0.2.0")
    assert not version_less_than("0.3.0", "0.2.0")


@patch("on1y.app_update.is_bundled_release", return_value=False)
def test_check_skipped_for_dev_build(_mock) -> None:
    report = check_app_update(force=True)
    assert report["check_enabled"] is False
    assert report["reason"] == "dev_build"
    assert report["has_update"] is False


@patch("on1y.app_update.is_bundled_release", return_value=True)
def test_check_app_update_with_mock_release(_mock) -> None:
    from on1y import app_update as mod

    mod._cache["expires_at"] = 0.0
    mod._cache["payload"] = None

    payload = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/S1jinCheng/ON1Y/releases/tag/v0.2.0",
        "body": "Bug fixes",
        "published_at": "2026-06-01T00:00:00Z",
        "assets": [
            {
                "name": "On1y_0.2.0_x64-setup.exe",
                "browser_download_url": "https://example.com/On1y_0.2.0_x64-setup.exe",
            }
        ],
    }

    with patch("on1y.app_update._fetch_latest_release", return_value=payload):
        report = check_app_update(force=True)

    assert report["check_enabled"] is True
    assert report["latest_version"] == "0.2.0"
    assert report["has_update"] is True
    assert report["download_url"].endswith("On1y_0.2.0_x64-setup.exe")
    assert report["release_notes"] == "Bug fixes"


def test_api_app_update_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    client = TestClient(create_app())
    response = client.get("/api/app/update")
    assert response.status_code == 200
    body = response.json()
    assert "current_version" in body
    assert "has_update" in body
