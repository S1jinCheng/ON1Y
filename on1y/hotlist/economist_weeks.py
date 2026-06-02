"""ISO week helpers and edition catalog for Economist hot-list."""

from __future__ import annotations

from datetime import date
from typing import Any

from on1y.config import Settings, get_settings
from on1y.hotlist.github_economist import fetch_economist_github_hotlist


def _week_label(*, iso_year: int, iso_week: int, edition_date: str, locale: str) -> str:
    if locale.lower().startswith("en"):
        return f"Week {iso_week} ({edition_date})"
    return f"第{iso_week}周（{edition_date}）"


def _edition_row(item: dict[str, Any], *, locale: str) -> dict[str, Any]:
    edition_date = str(item["edition_date"])
    d = date.fromisoformat(edition_date)
    iso_year, iso_week, _ = d.isocalendar()
    return {
        "edition_date": edition_date,
        "iso_year": iso_year,
        "iso_week": iso_week,
        "title": str(item.get("title") or ""),
        "epub_url": str(item.get("epub_url") or item.get("pdf_url") or item.get("url") or ""),
        "label": _week_label(iso_year=iso_year, iso_week=iso_week, edition_date=edition_date, locale=locale),
    }


def list_economist_editions(
    *,
    settings: Settings | None = None,
    year: int | None = None,
    locale: str = "zh",
) -> list[dict[str, Any]]:
    """All weekly editions from GitHub feed, optionally filtered by calendar year."""
    settings = settings or get_settings()
    raw_items = fetch_economist_github_hotlist(settings=settings, limit=120, snapshot_date=None)
    rows: list[dict[str, Any]] = []
    for item in raw_items:
        edition_date = str(item.get("edition_date") or item.get("heat_text") or "")
        if not edition_date:
            continue
        row = _edition_row(
            {
                **item,
                "edition_date": edition_date,
                "epub_url": item.get("epub_url") or item.get("pdf_url") or item.get("url"),
            },
            locale=locale,
        )
        if year is not None and int(row["iso_year"]) != year:
            continue
        rows.append(row)
    rows.sort(key=lambda r: (str(r["edition_date"])), reverse=True)
    return rows


def edition_for_iso_week(
    *,
    iso_year: int,
    iso_week: int,
    settings: Settings | None = None,
    locale: str = "zh",
) -> dict[str, Any] | None:
    for row in list_economist_editions(settings=settings, year=iso_year, locale=locale):
        if int(row["iso_week"]) == iso_week and int(row["iso_year"]) == iso_year:
            return row
    return None


def current_iso_week() -> tuple[int, int]:
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    return iso_year, iso_week
