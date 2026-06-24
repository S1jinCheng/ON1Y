from on1y.distill.prompts import theme_disambiguation_block


def test_theme_disambiguation_when_research_and_tech() -> None:
    themes = [
        {"slug": "research", "name_zh": "科研", "description_zh": "论文"},
        {"slug": "科技", "name_zh": "科技", "description_zh": "产业"},
    ]
    block = theme_disambiguation_block(themes, locale="zh")
    assert "科研" in block
    assert "科技" in block


def test_theme_disambiguation_skipped_without_tech() -> None:
    themes = [{"slug": "research", "name_zh": "科研", "description_zh": "论文"}]
    assert theme_disambiguation_block(themes, locale="zh") == ""
