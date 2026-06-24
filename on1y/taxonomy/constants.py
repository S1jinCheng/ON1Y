"""Default seed themes — runtime list lives in the database."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThemeDefinition:
    slug: str
    name_zh: str
    name_en: str
    sort_order: int
    description_zh: str = ""
    description_en: str = ""
    is_builtin: bool = False


DEFAULT_THEMES: tuple[ThemeDefinition, ...] = (
    ThemeDefinition(
        "hotlist",
        "热榜",
        "Hot List",
        15,
        "各平台每日热榜：知乎、经济学人、今日头条等聚合专栏。",
        "Daily hot lists from Zhihu, The Economist, Toutiao, and similar sources.",
    ),
    ThemeDefinition(
        "research",
        "科研",
        "Research",
        10,
        "学术论文、科研项目、实验设计与方法论、理工科基础研究；"
        "不含消费电子、产品发布、行业资讯或编程实战。",
        "Academic papers, research projects, experiments, and basic science; "
        "not consumer tech, product launches, or industry news.",
    ),
    ThemeDefinition(
        "cooking",
        "厨艺",
        "Cooking",
        20,
        "菜谱、烹饪技巧、食材与餐饮体验。",
        "Recipes, cooking techniques, ingredients, and food experiences.",
    ),
    ThemeDefinition(
        "history",
        "历史",
        "History",
        30,
        "世界史、中国史等史实与人物叙事；不含学科/行业的发展史。",
        "World and national historical events and narratives; not discipline histories.",
    ),
    ThemeDefinition(
        "film",
        "电影",
        "Film",
        40,
        "电影、纪录片、影视评论与观影笔记。",
        "Movies, documentaries, and film criticism.",
    ),
    ThemeDefinition(
        "comics",
        "漫画",
        "Comics",
        50,
        "漫画、动漫、插画与相关创作讨论。",
        "Comics, manga, anime, and illustration.",
    ),
    ThemeDefinition(
        "games",
        "游戏",
        "Games",
        60,
        "电子游戏、桌游、游戏设计与游玩体验。",
        "Video games, board games, and game design.",
    ),
    ThemeDefinition(
        "shopping",
        "购物",
        "Shopping",
        70,
        "消费决策、产品评测、购物清单与好物分享。",
        "Purchasing decisions, product reviews, and shopping lists.",
    ),
    ThemeDefinition(
        "economics",
        "经济",
        "Economics",
        80,
        "宏观经济、金融、商业与市场分析。",
        "Macroeconomics, finance, business, and markets.",
    ),
    ThemeDefinition(
        "news",
        "新闻",
        "News",
        90,
        "时事新闻、社会热点与公共事件报道。",
        "Current events, social issues, and news reporting.",
    ),
    ThemeDefinition(
        "philosophy",
        "哲学",
        "Philosophy",
        100,
        "哲学思想、伦理、认识论与精神探索。",
        "Philosophical ideas, ethics, epistemology, and reflection.",
    ),
    ThemeDefinition(
        "english",
        "英语",
        "English",
        110,
        "英语学习、语言技巧与英文原著阅读。",
        "English learning, language skills, and reading in English.",
    ),
    ThemeDefinition(
        "other",
        "其他",
        "Other",
        999,
        "无法明确归入以上任何主题的内容。",
        "Content that does not clearly fit any theme above.",
        is_builtin=True,
    ),
)

OTHER_THEME_SLUG = "other"

# User-created themes that share a slug with name_zh (e.g. 科技) — fill guidance if empty.
THEME_GUIDANCE_PATCHES: dict[str, dict[str, str]] = {
    "科技": {
        "description_zh": (
            "科技产业、数码硬件、软件应用、互联网、人工智能落地与行业动态；"
            "非学术论文或实验室科研。"
        ),
        "description_en": (
            "Tech industry, gadgets, software, internet, AI products, and industry news; "
            "not academic papers or lab research."
        ),
    },
}


def theme_label(row: dict[str, object], locale: str) -> str:
    if locale.lower().startswith("en"):
        return str(row.get("name_en") or row.get("slug") or "")
    return str(row.get("name_zh") or row.get("slug") or "")


def slugify_theme_name(name: str) -> str:
    import re

    base = name.strip().lower()
    base = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE)
    base = re.sub(r"[\s_]+", "-", base).strip("-")
    return base or "theme"
