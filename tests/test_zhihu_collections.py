"""Tests for Zhihu collection URL helpers."""

from on1y.ingestion.zhihu_collections import content_to_url, normalize_zhihu_item_url


def test_normalize_pin_url() -> None:
    url = "https://www.zhihu.com/pin/123?native=0"
    assert normalize_zhihu_item_url(url) == "https://www.zhihu.com/pin/123"


def test_content_to_url_answer() -> None:
    content = {
        "type": "answer",
        "url": "https://www.zhihu.com/question/1/answer/2",
    }
    assert content_to_url(content) == "https://www.zhihu.com/question/1/answer/2"


def test_content_to_url_article() -> None:
    content = {
        "type": "article",
        "url": "https://zhuanlan.zhihu.com/p/74249758",
    }
    assert content_to_url(content) == "https://zhuanlan.zhihu.com/p/74249758"
