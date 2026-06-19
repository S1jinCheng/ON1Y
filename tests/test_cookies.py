"""Cookie file loading tests."""

import json

import pytest
from on1y.browser.cookies import (
    is_cookie_list,
    is_storage_state,
    load_cookie_file,
    normalize_cookie_list,
    normalize_storage_state,
)
from on1y.exceptions import ConfigurationError


def test_storage_state_detection() -> None:
    assert is_storage_state({"cookies": [], "origins": []})
    assert not is_storage_state({"cookies": []})


def test_cookie_list_detection() -> None:
    assert is_cookie_list([{"name": "a", "value": "b", "domain": ".zhihu.com"}])


def test_load_missing_file(tmp_path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_cookie_file(tmp_path / "missing.json")


def test_load_cookie_list_file(tmp_path) -> None:
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps([{"name": "t", "value": "1", "domain": ".zhihu.com", "path": "/"}]),
        encoding="utf-8",
    )
    data = load_cookie_file(path)
    assert is_cookie_list(data)
    normalized = normalize_cookie_list(data, ".zhihu.com")
    assert normalized[0]["name"] == "t"


def test_normalize_storage_state_strips_null_same_site() -> None:
    data = {
        "cookies": [
            {
                "name": "z_c0",
                "value": "secret",
                "domain": ".zhihu.com",
                "path": "/",
                "sameSite": None,
                "expirationDate": 1795499276.0,
                "hostOnly": False,
            }
        ],
        "origins": [],
    }
    out = normalize_storage_state(data)
    cookie = out["cookies"][0]
    assert "sameSite" not in cookie
    assert cookie["expires"] == 1795499276.0
    assert "hostOnly" not in cookie
    assert "expirationDate" not in cookie


def test_normalize_storage_state_maps_unspecified_same_site() -> None:
    data = {
        "cookies": [
            {
                "name": "a",
                "value": "1",
                "domain": ".zhihu.com",
                "path": "/",
                "sameSite": "unspecified",
            }
        ],
        "origins": [],
    }
    out = normalize_storage_state(data)
    assert "sameSite" not in out["cookies"][0]


def test_registry_social_before_article() -> None:
    from on1y.extract.article import ArticleExtractor
    from on1y.extract.registry import ExtractorRegistry
    from on1y.extract.zhihu import ZhihuExtractor

    registry = ExtractorRegistry([ZhihuExtractor(), ArticleExtractor()])
    assert registry.resolve("https://www.zhihu.com/p/1").name == "zhihu"
