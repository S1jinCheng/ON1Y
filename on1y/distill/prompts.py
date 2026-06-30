"""Prompt templates for exclusive theme + flat dynamic tags."""

from __future__ import annotations

from typing import Any

from on1y.taxonomy.constants import KNOWN_THEME_PAIRS, theme_label

PROMPT_VERSION = "v4-exclusive"
EVENING_DIGEST_PROMPT_VERSION = "v1-news-md"


def themes_block_for_prompt(themes: list[dict[str, Any]], *, locale: str) -> str:
    lines: list[str] = []
    for theme in themes:
        slug = str(theme["slug"])
        if locale.lower().startswith("en"):
            desc = str(theme.get("description_en") or "")
            lines.append(f'- "{slug}": {theme.get("name_en")} — {desc}')
        else:
            desc = str(theme.get("description_zh") or "")
            lines.append(f'- "{slug}": {theme.get("name_zh")} — {desc}')
    return "\n".join(lines)


def collect_active_disambiguation_pairs(
    themes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pairs from KNOWN_THEME_PAIRS where both themes are active."""
    by_slug = {str(theme["slug"]).lower(): theme for theme in themes}
    name_to_slug: dict[str, str] = {}
    for theme in themes:
        slug = str(theme["slug"]).lower()
        name_to_slug[slug] = slug
        name_zh = str(theme.get("name_zh") or "").strip()
        if name_zh:
            name_to_slug[name_zh] = slug
            name_to_slug[name_zh.casefold()] = slug

    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for theme in themes:
        slug = str(theme["slug"]).lower()
        lookup_keys = {slug, str(theme.get("name_zh") or "").strip().casefold()}
        known: list[Any] = []
        for map_key, map_pairs in KNOWN_THEME_PAIRS.items():
            if map_key.casefold() in lookup_keys or map_key == slug:
                known.extend(map_pairs)
        for pair in known:
            resolved_peer = name_to_slug.get(pair.peer_slug)
            if resolved_peer is None:
                resolved_peer = name_to_slug.get(pair.peer_slug.casefold())
            if resolved_peer is None or resolved_peer not in by_slug:
                continue
            ordered = tuple(sorted((slug, resolved_peer)))
            if ordered in seen:
                continue
            seen.add(ordered)
            pairs.append(
                {
                    "slug_a": slug,
                    "slug_b": resolved_peer,
                    "theme_a": theme,
                    "theme_b": by_slug[resolved_peer],
                    "a_when": pair.new_theme_when,
                    "b_when": pair.peer_when,
                }
            )
    return pairs


def build_disambiguation_block(
    pairs: list[dict[str, Any]],
    *,
    locale: str,
) -> str:
    if not pairs:
        return ""
    lines: list[str] = []
    if locale.lower().startswith("en"):
        lines.append("Theme disambiguation (do not confuse these pairs):")
    else:
        lines.append("主题辨析（以下主题对不可混淆）：")
    for pair in pairs:
        theme_a = pair["theme_a"]
        theme_b = pair["theme_b"]
        slug_a = str(pair["slug_a"])
        slug_b = str(pair["slug_b"])
        name_a = theme_label(theme_a, locale)
        name_b = theme_label(theme_b, locale)
        a_when = str(pair.get("a_when") or "").strip()
        b_when = str(pair.get("b_when") or "").strip()
        if locale.lower().startswith("en"):
            lines.append(f'- "{slug_a}" ({name_a}): {a_when or "see theme description"}')
            lines.append(f'- "{slug_b}" ({name_b}): {b_when or "see theme description"}')
        else:
            lines.append(f'- "{slug_a}"（{name_a}）：{a_when or "见主题描述"}')
            lines.append(f'- "{slug_b}"（{name_b}）：{b_when or "见主题描述"}')
    return "\n" + "\n".join(lines) + "\n"


def build_absorb_disambiguation_block(
    disambiguation: list[dict[str, Any]],
    *,
    theme: dict[str, Any],
    themes_by_slug: dict[str, dict[str, Any]],
    locale: str,
) -> str:
    if not disambiguation:
        return ""
    new_slug = str(theme["slug"]).lower()
    lines: list[str] = []
    if locale.lower().startswith("en"):
        lines.append("Theme disambiguation for this absorb pass:")
    else:
        lines.append("本次迁入的主题辨析：")
    for item in disambiguation:
        peer_slug = str(item.get("peer_slug") or "").lower()
        peer = themes_by_slug.get(peer_slug)
        if peer is None:
            continue
        new_name = theme_label(theme, locale)
        peer_name = theme_label(peer, locale)
        new_when = str(item.get("new_theme_when") or "").strip()
        peer_when = str(item.get("peer_when") or "").strip()
        if locale.lower().startswith("en"):
            lines.append(f'- "{new_slug}" ({new_name}): {new_when}')
            lines.append(f'- "{peer_slug}" ({peer_name}): {peer_when}')
        else:
            lines.append(f'- "{new_slug}"（{new_name}）：{new_when}')
            lines.append(f'- "{peer_slug}"（{peer_name}）：{peer_when}')
    if len(lines) <= 1:
        return ""
    return "\n" + "\n".join(lines) + "\n"


def theme_disambiguation_block(themes: list[dict[str, Any]], *, locale: str) -> str:
    pairs = collect_active_disambiguation_pairs(themes)
    return build_disambiguation_block(pairs, locale=locale)


def build_system_prompt(*, locale: str, themes: list[dict[str, Any]]) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    theme_block = themes_block_for_prompt(themes, locale=locale)
    disambiguation = theme_disambiguation_block(themes, locale=locale)
    return f"""You classify content for a personal knowledge archive. Respond in {lang} only.

Return ONE JSON object (no markdown):
{{
  "summary": "1-2 short sentences: core takeaway",
  "theme": "research",
  "tags": ["tag1", "tag2", "tag3"]
}}

Fixed themes (pick exactly ONE slug — mutually exclusive buckets):
{theme_block}
{disambiguation}
Rules:
- theme: exactly ONE slug from the list. Choose by dominant topic weight, not minor mentions.
- If uncertain, use "other".
- tags: 3-8 precise flat dynamic labels (like online book tags). No hierarchy.
- Do NOT put theme names or author/creator names into tags.
- summary: MAX 2 sentences.
- Be factual; do not invent.
- ALL text fields must be in {lang}."""


def build_reader_system_prompt(*, locale: str) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    return f"""Rewrite video subtitle/caption text as clean readable prose in {lang}.
Preserve meaning; remove timestamps and duplicate lines; use paragraphs.
Return plain text only (no JSON, no markdown fences). Max ~1200 words."""


def build_conversation_reader_prompt(*, locale: str) -> str:
    """Write up a 1-on-1 chat transcript as connected, de-noised prose."""
    if locale.lower().startswith("en"):
        return (
            "Rewrite the following 1-on-1 chat transcript as a clean, connected "
            "written account in English.\n"
            "Goals:\n"
            "- Preserve who said what, both sides' viewpoints, their reasoning, "
            "and any conclusions reached.\n"
            "- Merge fragmented bursts into coherent paragraphs; remove greetings, "
            "filler, stickers, and entertainment noise.\n"
            "- Keep it faithful: do NOT invent facts or opinions.\n"
            "- Use the speaker's name or 'I' to attribute key points where it matters.\n"
            "Return plain text only (no JSON, no markdown fences). Max ~1200 words."
        )
    return (
        "把下面这段一对一聊天记录改写成连贯、书面化的交流纪要（用中文）。\n"
        "要求：\n"
        "- 保留谁说了什么、双方的观点、论证过程，以及最终达成或未达成的结论。\n"
        "- 把零碎的对话合并成连贯段落；去掉寒暄、口头禅、表情、贴纸等娱乐噪声。\n"
        "- 必须忠实，不得编造事实或观点。\n"
        "- 在关键观点处用说话人姓名或「我」标明归属。\n"
        "只返回纯文本（不要 JSON，不要 markdown 代码块）。不超过约 1200 字。"
    )


def build_evening_digest_system_prompt(
    *,
    locale: str,
    max_crux: int,
    max_chars: int,
) -> str:
    if locale.lower().startswith("en"):
        return (
            "You are the editor of a top-tier daily intelligence brief.\n"
            "Return Markdown only.\n"
            "This is a rapid briefing, not a long-form report.\n"
            "Use a human article style with clear rhythm, line breaks, and strong readability.\n"
            "Do NOT force fixed sections like domestic/international/technology.\n"
            "Instead, infer 3-5 meaningful modules from today's signals, "
            "and title each module clearly.\n"
            "Recommended structure:\n"
            "# Evening Brief | YYYY-MM-DD\n"
            "> Optional one-line quote as opening hook\n"
            "— quote attribution (small text style by UI)\n"
            "**Lead summary (40-80 words).**\n"
            "## Module title A\n"
            "- bullets\n"
            "---\n"
            "## Module title B\n"
            "- bullets\n"
            "Bullet constraints:\n"
            "- Each bullet must follow: Subject + Action + Core result.\n"
            "- Bold key numbers/time windows/amounts, e.g. **30%**, **200 bn**, **4-6 weeks**.\n"
            "- Keep each bullet concise and factual.\n"
            "- Do NOT write dashboard-style lines about totals/read counts/"
            "unread pool/theme shares.\n"
            "- After a core bullet, you may add one 'Details:' line with fuller context.\n"
            "- Format details line exactly as: Details: ...\n"
            "- End each core bullet with one compact source token: [ref](URL).\n"
            "- Do NOT add words like 'Source' or 'original link'.\n"
            "- If a relevant image URL exists, append one markdown image line "
            "right below that bullet.\n"
            f"Hard limit: <= {max_chars} characters total."
        )
    return (
        "你是顶级新闻编辑部的晚报主编。\n"
        "仅输出 Markdown。\n"
        "这是资讯速递，不是深度报道。\n"
        "使用人类写作风格：有标题、有简短引子，节奏清晰，换行自然。\n"
        "不要强行使用“国内/国际/科技”等固定分区。\n"
        "应根据当天信息自行归纳 3-5 个模块，并用二级标题命名模块。\n"
        "建议结构：\n"
        "# 今日晚报 | YYYY-MM-DD\n"
        "> 可选一句名言/引言（1行）\n"
        "— 引言署名（前端会显示为小字号）\n"
        "**开场总结（40-80字）**\n"
        "## 模块A（模型自行命名）\n"
        "- 若干条资讯\n"
        "---\n"
        "## 模块B（模型自行命名）\n"
        "- 若干条资讯\n"
        "每条资讯硬约束：\n"
        "- 必须严格符合“主语 + 动作 + 核心结果”。\n"
        "- 关键数字、比例、金额、时间窗必须加粗，如 **30%**、**2000亿元**、**4-6周**。\n"
        "- 不展开背景科普，不写长段解释。\n"
        "- 禁止写“今日X篇、已读X篇、未读X篇、主题占比”等仪表盘统计句。\n"
        "- 在核心事件后可追加一行“细节：...”，补充完整详情。\n"
        "- 细节行格式必须是：细节：...\n"
        "- 每条核心资讯末尾都要放一个精简链接标记：[ref](URL)。\n"
        "- 不要写“原文”“链接”“来源”等文字说明。\n"
        "- 模块之间要有空行，并优先用 `---` 分割。\n"
        "- 引言署名若为外国人，请附原名（例如：马斯克 Elon Musk）。\n"
        "- 如果有合适的配图链接（image_url），可在该条下方附一行 Markdown 图片。\n"
        f"总字数不超过 {max_chars} 字。"
    )


def build_evening_digest_user_prompt(*, stats: dict[str, Any], locale: str) -> str:
    lines = [
        f"prompt_version: {EVENING_DIGEST_PROMPT_VERSION}",
        f"date: {stats['digest_date']}",
        f"selection_meta: {stats.get('selection_meta')}",
        "highlights:",
    ]
    for item in stats.get("highlights") or []:
        lines.append(
            f"- [{item['platform']}] [{item.get('theme_slug', 'other')}] {item['title']} "
            f"(read={item['is_read']}, score={item.get('score', 0)}) {item.get('summary') or ''}"
        )
        if item.get("url"):
            lines.append(f"  source_url: {item['url']}")
        if item.get("image_url"):
            lines.append(f"  image_url: {item['image_url']}")
    if locale.lower().startswith("en"):
        lines.insert(0, "Write today's evening brief using the following structured data:")
    else:
        lines.insert(0, "请根据以下结构化数据撰写今天的晚报：")
    return "\n".join(lines)
