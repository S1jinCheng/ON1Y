"""Tests for Zhihu title helpers."""

from on1y.utils.zhihu_title import clean_rss_entry_title, resolve_zhihu_title, strip_html


def test_strip_html() -> None:
    assert strip_html("<p>你好</p>") == "你好"


def test_clean_rss_pin_entry() -> None:
    entry = (
        '苏剑林发布了想法: <p>《为什么官方版Muon比MuP版多出一个max(1, ⋅)？》'
        '<a href="https://link.zhihu.com/">链接</a></p>'
    )
    assert clean_rss_entry_title(entry) == "为什么官方版Muon比MuP版多出一个max(1, ⋅)？"


def test_clean_rss_agree_entry() -> None:
    entry = '李博杰赞同了想法: Codex App 在 Mac 上卡到风扇狂转？<br /><p>好</p>'
    assert "Codex App" in clean_rss_entry_title(entry)


def test_resolve_prefers_question_from_entry(monkeypatch) -> None:
    monkeypatch.setattr(
        "on1y.utils.zhihu_title.fetch_zhihu_title_for_url",
        lambda *_a, **_k: "API 标题",
    )
    title = resolve_zhihu_title(
        "https://www.zhihu.com/question/1/answer/2",
        "",
        {"entry_title": "可以说一个比较小众的冷知识吗？"},
        fetch_api=False,
    )
    assert title == "可以说一个比较小众的冷知识吗？"
