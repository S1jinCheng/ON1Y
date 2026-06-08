"""Background Economist edition watch: ingest + optional Kindle delivery."""

from __future__ import annotations

import logging
import threading
from typing import Any

from on1y.config import Settings, get_settings
from on1y.hotlist.economist import sync_economist_hotlist
from on1y.hotlist.github_economist import fetch_latest_economist_edition
from on1y.auth.context import user_context
from on1y.user.profile import kindle_delivery_address, load_user_profile, patch_user_profile

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()


def start_economist_auto_loop() -> None:
    global _thread
    from on1y.sync_settings.settings import any_economist_auto_sync_enabled, min_economist_sync_interval_minutes

    if not any_economist_auto_sync_enabled():
        return
    profile = load_user_profile()
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="on1y-economist-auto", daemon=True)
    _thread.start()
    logger.info(
        "Economist auto-ingest enabled (every %s min, Kindle=%s)",
        min_economist_sync_interval_minutes(),
        profile["economist"]["auto_kindle_enabled"],
    )


def stop_economist_auto_loop() -> None:
    _stop.set()


def run_economist_auto_tick(
    *,
    force_edition: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Check GitHub for a new weekly edition; ingest into DB; optionally email Kindle."""
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.delivery.kindle import send_epub_to_kindle
    from on1y.hotlist.epub_preview import resolve_economist_epub_cache_path
    from on1y.user.accounts import list_sync_user_ids

    settings = get_settings()
    storage = get_storage()
    try:
        user_ids = [user_id] if user_id is not None else list_sync_user_ids(storage)
    finally:
        storage.close()

    if not user_ids:
        return {"skipped": True, "reason": "no_users"}

    merged: dict[str, Any] = {"users": []}
    for uid in user_ids:
        with user_context(uid):
            merged["users"].append(_run_economist_auto_tick_for_user(force_edition=force_edition))
    if len(merged["users"]) == 1:
        return merged["users"][0]
    return merged


def _run_economist_auto_tick_for_user(*, force_edition: str | None = None) -> dict[str, Any]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.delivery.kindle import send_epub_to_kindle
    from on1y.hotlist.epub_preview import resolve_economist_epub_cache_path

    from on1y.sync_settings.settings import resolve_settings

    settings = resolve_settings()
    profile = load_user_profile()
    if not settings.economist_auto_sync_enabled and not force_edition:
        return {
            "skipped": True,
            "reason": "economist_auto_sync_disabled",
            "edition_date": None,
            "ingested": False,
            "kindle_sent": False,
            "errors": [],
        }
    report: dict[str, Any] = {
        "skipped": False,
        "edition_date": None,
        "ingested": False,
        "kindle_sent": False,
        "errors": [],
    }

    if not profile["economist"]["auto_ingest_enabled"] and not force_edition:
        report["skipped"] = True
        report["reason"] = "auto_ingest_disabled"
        return report

    try:
        if force_edition:
            edition_date = force_edition.strip()
            latest = {"edition_date": edition_date, "title": f"经济学人 {edition_date}"}
        else:
            latest = fetch_latest_economist_edition(settings=settings)
    except Exception as exc:
        report["errors"].append(f"fetch: {exc}")
        return report

    if not latest:
        report["skipped"] = True
        report["reason"] = "no_edition_found"
        return report

    edition_date = str(latest.get("edition_date") or "").strip()
    report["edition_date"] = edition_date
    if not edition_date:
        report["skipped"] = True
        report["reason"] = "missing_edition_date"
        return report

    last_synced = str(profile["economist"].get("last_synced_edition") or "").strip()
    if not force_edition and edition_date == last_synced:
        report["skipped"] = True
        report["reason"] = "already_synced"
        return report

    storage = get_storage()
    try:
        sync_report = sync_economist_hotlist(
            storage,
            settings=settings,
            snapshot_date=edition_date,
            auto_tag=settings.economist_hotlist_auto_tag,
        )
        econ = sync_report
        created = int(econ.get("created") or 0)
        updated = int(econ.get("updated") or 0)
        errors = list(econ.get("errors") or [])
        if errors:
            report["errors"].extend(errors)
        if created > 0 or updated > 0 or not errors:
            report["ingested"] = True
            patch_user_profile(
                economist={
                    "last_synced_edition": edition_date,
                }
            )
            profile = load_user_profile()
    finally:
        storage.close()

    kindle_enabled = bool(profile["economist"].get("auto_kindle_enabled"))
    kindle_to = kindle_delivery_address(profile)
    last_kindle = str(profile["economist"].get("last_kindle_edition") or "").strip()

    if (
        report["ingested"]
        and kindle_enabled
        and kindle_to
        and (force_edition or edition_date != last_kindle)
    ):
        cache = resolve_economist_epub_cache_path(settings, edition_date)
        if cache is not None:
            title = str(latest.get("title") or f"The Economist {edition_date}")
            try:
                send_epub_to_kindle(
                    cache,
                    to_address=kindle_to,
                    subject=title,
                    settings=settings,
                )
                report["kindle_sent"] = True
                patch_user_profile(economist={"last_kindle_edition": edition_date})
            except Exception as exc:
                logger.warning("Kindle send failed: %s", exc)
                report["errors"].append(f"kindle: {exc}")
        else:
            report["errors"].append("kindle: EPUB cache missing after ingest")

    return report


def _loop() -> None:  # noqa: C901 — background loop
    from on1y.sync_settings.settings import min_economist_sync_interval_minutes

    interval = min_economist_sync_interval_minutes() * 60
    while not _stop.is_set():
        if _stop.wait(timeout=interval):
            break
        try:
            report = run_economist_auto_tick()
            if report.get("ingested"):
                logger.info(
                    "Economist auto: ingested %s kindle=%s",
                    report.get("edition_date"),
                    report.get("kindle_sent"),
                )
            elif report.get("skipped"):
                logger.debug("Economist auto skipped: %s", report.get("reason"))
            elif report.get("errors"):
                logger.warning("Economist auto errors: %s", report["errors"])
        except Exception:
            logger.exception("Economist auto tick failed")
