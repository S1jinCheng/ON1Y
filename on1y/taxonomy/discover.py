"""Discover related themes and prefilter absorb candidates."""

from __future__ import annotations

import logging
import re
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.hotlist.constants import HOTLIST_THEME_SLUG
from on1y.llm.client import get_llm_client
from on1y.taxonomy.constants import (
    ABSORB_RELATION_CATCH_ALL,
    ABSORB_RELATION_DISAMBIGUATION_PEER,
    DEFAULT_PREFILTER_MIN_SCORE,
    KNOWN_THEME_PAIRS,
    OTHER_THEME_SLUG,
    PEER_PREFILTER_MIN_SCORE,
    KnownThemePair,
    theme_label,
)

logger = logging.getLogger(__name__)

_SCAN_RELATIONS = frozenset(
    {
        ABSORB_RELATION_DISAMBIGUATION_PEER,
        "subset_source",
        "superset_source",
    }
)


def _theme_keys(theme: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("slug", "name_zh", "name_en"):
        value = str(theme.get(field) or "").strip()
        if value:
            keys.add(value.casefold())
    return keys


def _resolve_peer_slug(peer_slug: str, themes_by_slug: dict[str, dict[str, Any]]) -> str | None:
    normalized = peer_slug.strip().lower()
    if normalized in themes_by_slug:
        return normalized
    for slug, row in themes_by_slug.items():
        if str(row.get("name_zh") or "").strip() == peer_slug.strip():
            return slug
    return None


def _known_pairs_for_theme(theme: dict[str, Any]) -> list[KnownThemePair]:
    pairs: list[KnownThemePair] = []
    for key in _theme_keys(theme):
        pairs.extend(KNOWN_THEME_PAIRS.get(key, ()))
        if key in KNOWN_THEME_PAIRS:
            continue
        lower_key = key.lower()
        if lower_key in KNOWN_THEME_PAIRS:
            pairs.extend(KNOWN_THEME_PAIRS[lower_key])
    return pairs


def _merge_disambiguation(
    existing: list[dict[str, Any]],
    peer_slug: str,
    pair: KnownThemePair,
    *,
    new_slug: str,
) -> list[dict[str, Any]]:
    for item in existing:
        if str(item.get("peer_slug") or "").lower() == peer_slug.lower():
            return existing
    existing.append(
        {
            "peer_slug": peer_slug,
            "new_theme_when": pair.new_theme_when,
            "peer_when": pair.peer_when,
            "new_slug": new_slug,
        }
    )
    return existing


def merge_known_pairs(
    discovery: dict[str, Any],
    *,
    theme: dict[str, Any],
    themes_by_slug: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Union LLM discovery with KNOWN_THEME_PAIRS (known pairs are never dropped)."""
    new_slug = str(theme["slug"]).lower()
    scan_sources: list[dict[str, Any]] = list(discovery.get("scan_sources") or [])
    disambiguation: list[dict[str, Any]] = list(discovery.get("disambiguation") or [])
    by_slug: dict[str, dict[str, Any]] = {
        str(item.get("slug") or "").lower(): item for item in scan_sources if item.get("slug")
    }

    for pair in _known_pairs_for_theme(theme):
        resolved = _resolve_peer_slug(pair.peer_slug, themes_by_slug)
        if resolved is None or resolved == new_slug:
            continue
        current = by_slug.get(resolved)
        if current is None:
            by_slug[resolved] = {
                "slug": resolved,
                "relation": pair.relation,
                "confidence": pair.confidence,
                "priority": 10,
            }
        else:
            current["confidence"] = max(
                float(current.get("confidence") or 0),
                pair.confidence,
            )
            if pair.relation == ABSORB_RELATION_DISAMBIGUATION_PEER:
                current["relation"] = ABSORB_RELATION_DISAMBIGUATION_PEER
        if pair.relation == ABSORB_RELATION_DISAMBIGUATION_PEER:
            disambiguation = _merge_disambiguation(
                disambiguation,
                resolved,
                pair,
                new_slug=new_slug,
            )

    scan_sources = sorted(
        by_slug.values(),
        key=lambda item: (int(item.get("priority") or 50), str(item.get("slug"))),
    )
    keywords = list(discovery.get("keywords") or [])
    if not keywords:
        keywords = _fallback_keywords(theme)
    return {
        "keywords": keywords,
        "scan_sources": scan_sources,
        "disambiguation": disambiguation,
    }


def _fallback_keywords(theme: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(theme.get(field) or "")
        for field in ("name_zh", "name_en", "description_zh", "description_en", "slug")
    )
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", text, flags=re.UNICODE)
    seen: set[str] = set()
    keywords: list[str] = []
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(token)
        if len(keywords) >= 8:
            break
    return keywords


def build_discovery_system_prompt(*, locale: str) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    return f"""You analyze theme taxonomy for a personal knowledge archive. Respond in {lang} only.

Return ONE JSON object (no markdown):
{{
  "keywords": ["term1", "term2"],
  "scan_sources": [
    {{"slug": "research", "relation": "disambiguation_peer", "confidence": 0.9, "priority": 10}}
  ],
  "disambiguation": [
    {{
      "peer_slug": "research",
      "new_theme_when": "when content fits the NEW theme",
      "peer_when": "when content fits the peer theme",
      "examples": [{{"text": "example title", "belongs": "new"}}]
    }}
  ]
}}

Relation types for scan_sources (only themes that may contain misclassified items for the NEW theme):
- disambiguation_peer: high semantic overlap, easily confused (e.g. 科技 vs 科研)
- subset_source: NEW theme is narrower; a broader existing theme may wrongly hold items
- superset_source: NEW theme is broader; a narrower existing theme may wrongly hold items

Rules:
- keywords: 3-8 core terms/phrases for the NEW theme (for prefiltering).
- Do NOT include orthogonal/unrelated themes (e.g. economics vs shopping).
- Do NOT include the NEW theme slug or "{OTHER_THEME_SLUG}" (other is always scanned separately).
- confidence: 0.0-1.0; only include scan_sources with confidence >= 0.6.
- disambiguation: only for disambiguation_peer pairs in scan_sources.
- If no related themes exist besides other, return empty scan_sources and disambiguation."""


def build_discovery_user_prompt(
    *,
    theme: dict[str, Any],
    existing_themes: list[dict[str, Any]],
    locale: str,
) -> str:
    new_slug = str(theme["slug"])
    if locale.lower().startswith("en"):
        new_name = str(theme.get("name_en") or new_slug)
        new_desc = str(theme.get("description_en") or theme.get("name_en") or "")
    else:
        new_name = str(theme.get("name_zh") or new_slug)
        new_desc = str(theme.get("description_zh") or theme.get("name_zh") or "")
    lines = []
    for row in existing_themes:
        slug = str(row["slug"])
        label = theme_label(row, locale)
        if locale.lower().startswith("en"):
            desc = str(row.get("description_en") or "")
        else:
            desc = str(row.get("description_zh") or "")
        lines.append(f'- "{slug}": {label} — {desc}')
    existing_block = "\n".join(lines) if lines else "(none)"
    return f"""NEW THEME:
- slug: "{new_slug}"
- name: {new_name}
- description: {new_desc or "(none)"}

EXISTING THEMES (candidates for misclassification sources):
{existing_block}"""


def discover_related_themes(
    storage: SqliteStorage,
    *,
    theme: dict[str, Any],
    locale: str,
    confidence_threshold: float = 0.6,
) -> dict[str, Any]:
    """Phase 1: one LLM call to find related source themes + keywords."""
    new_slug = str(theme["slug"]).lower()
    active = storage.list_active_themes()
    themes_by_slug = {str(row["slug"]).lower(): row for row in active}
    peer_themes = [
        row
        for row in active
        if str(row["slug"]).lower()
        not in {new_slug, OTHER_THEME_SLUG, HOTLIST_THEME_SLUG}
    ]

    try:
        client = get_llm_client()
        parsed = client.chat_json(
            build_discovery_system_prompt(locale=locale),
            build_discovery_user_prompt(
                theme=theme,
                existing_themes=peer_themes,
                locale=locale,
            ),
        )
    except Exception as exc:
        logger.warning("Theme discovery LLM failed for %s: %s", new_slug, exc)
        parsed = {"keywords": [], "scan_sources": [], "disambiguation": []}

    scan_sources: list[dict[str, Any]] = []
    for item in parsed.get("scan_sources") or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip().lower()
        if not slug or slug in {new_slug, OTHER_THEME_SLUG, HOTLIST_THEME_SLUG}:
            continue
        if slug not in themes_by_slug:
            continue
        relation = str(item.get("relation") or "").strip()
        if relation not in _SCAN_RELATIONS:
            continue
        confidence = float(item.get("confidence") or 0)
        if confidence < confidence_threshold:
            continue
        scan_sources.append(
            {
                "slug": slug,
                "relation": relation,
                "confidence": confidence,
                "priority": int(item.get("priority") or 50),
            }
        )

    disambiguation: list[dict[str, Any]] = []
    for item in parsed.get("disambiguation") or []:
        if not isinstance(item, dict):
            continue
        peer_slug = str(item.get("peer_slug") or "").strip().lower()
        resolved = _resolve_peer_slug(peer_slug, themes_by_slug)
        if resolved is None:
            continue
        disambiguation.append(
            {
                "peer_slug": resolved,
                "new_theme_when": str(item.get("new_theme_when") or ""),
                "peer_when": str(item.get("peer_when") or ""),
                "new_slug": new_slug,
                "examples": item.get("examples") or [],
            }
        )

    discovery = merge_known_pairs(
        {
            "keywords": parsed.get("keywords") or [],
            "scan_sources": scan_sources,
            "disambiguation": disambiguation,
        },
        theme=theme,
        themes_by_slug=themes_by_slug,
    )
    if not discovery["keywords"]:
        discovery["keywords"] = _fallback_keywords(theme)
    return discovery


def _score_text(text: str, keywords: list[str]) -> int:
    if not text.strip() or not keywords:
        return 0
    lowered = text.casefold()
    score = 0
    for keyword in keywords:
        key = keyword.strip()
        if len(key) < 2:
            continue
        if key.casefold() in lowered:
            score += 3 if len(key) >= 4 else 2
    return score


def score_item_for_prefilter(
    storage: SqliteStorage,
    raw_id: int,
    keywords: list[str],
) -> int:
    raw = storage.get_raw_by_id(raw_id)
    if raw is None:
        return 0
    score = _score_text(raw.raw_title or "", keywords) * 1
    distilled = storage.get_distilled_by_raw_id(raw_id)
    if distilled and distilled.summary:
        score += _score_text(distilled.summary, keywords) * 2
    tags = storage.get_item_tag_names(raw_id)
    for tag in tags:
        score += _score_text(tag, keywords) * 2
    body = (raw.body_text or "")[:500]
    score += _score_text(body, keywords)
    return score


def prefilter_candidates(
    storage: SqliteStorage,
    raw_ids: list[int],
    keywords: list[str],
    *,
    relation: str,
    max_candidates: int,
) -> tuple[list[int], int]:
    """Phase 2: keyword/tag prefilter for non-other source themes."""
    min_score = (
        PEER_PREFILTER_MIN_SCORE
        if relation == ABSORB_RELATION_DISAMBIGUATION_PEER
        else DEFAULT_PREFILTER_MIN_SCORE
    )
    scored: list[tuple[int, int]] = []
    for raw_id in raw_ids:
        score = score_item_for_prefilter(storage, raw_id, keywords)
        if score >= min_score:
            scored.append((raw_id, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    total_hits = len(scored)
    if max_candidates > 0:
        scored = scored[:max_candidates]
    return [raw_id for raw_id, _ in scored], total_hits


def build_scan_plan(
    discovery: dict[str, Any],
    *,
    themes_by_slug: dict[str, dict[str, Any]],
    forced_source_slugs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Ordered absorb sources: other first, then related themes."""
    plan: list[dict[str, Any]] = [
        {
            "slug": OTHER_THEME_SLUG,
            "relation": ABSORB_RELATION_CATCH_ALL,
            "prefilter": False,
        }
    ]
    seen = {OTHER_THEME_SLUG}
    for slug in forced_source_slugs or []:
        normalized = slug.strip().lower()
        if normalized in seen or normalized not in themes_by_slug:
            continue
        seen.add(normalized)
        plan.append(
            {
                "slug": normalized,
                "relation": ABSORB_RELATION_DISAMBIGUATION_PEER,
                "prefilter": False,
            }
        )
    for item in discovery.get("scan_sources") or []:
        slug = str(item.get("slug") or "").lower()
        if slug in seen or slug not in themes_by_slug:
            continue
        seen.add(slug)
        plan.append(
            {
                "slug": slug,
                "relation": str(item.get("relation") or ""),
                "prefilter": True,
            }
        )
    return plan
