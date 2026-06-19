"""Zhihu API subscription helpers."""

from __future__ import annotations

from on1y.ingestion.zhihu_subscriptions import _target_title, _target_url


def test_target_url_answer() -> None:
    url = _target_url(
        {
            "type": "answer",
            "id": 123,
            "question": {"id": 456, "title": "Hello?"},
        }
    )
    assert url == "https://www.zhihu.com/question/456/answer/123"


def test_target_url_ignores_api_zhihu_url() -> None:
    url = _target_url(
        {
            "type": "answer",
            "id": 123,
            "url": "https://api.zhihu.com/answers/123",
            "question": {"id": 456, "title": "Hello?"},
        }
    )
    assert url == "https://www.zhihu.com/question/456/answer/123"


def test_target_url_article() -> None:
    url = _target_url({"type": "article", "id": 99})
    assert url == "https://zhuanlan.zhihu.com/p/99"


def test_target_title_from_question() -> None:
    title = _target_title(
        {
            "type": "answer",
            "question": {"title": "如何学习 Python"},
            "excerpt": "ignored",
        }
    )
    assert title == "如何学习 Python"
