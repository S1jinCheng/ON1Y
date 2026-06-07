"""Export / import per-user knowledge library as a portable .on1y.zip bundle."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from on1y.auth.context import user_context
from on1y.hotlist.sql import is_feed_row_sql
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.utils.json_util import loads_json_list, loads_meta

ARCHIVE_FORMAT = "on1y-archive"
ARCHIVE_VERSION = 1
MANIFEST_NAME = "manifest.json"
ITEMS_NAME = "items.jsonl"
THEMES_NAME = "themes.json"
SETTINGS_SUBSCRIPTION = "settings/subscription.json"
SETTINGS_PROFILE = "settings/profile.json"
SETTINGS_COOKIES_PREFIX = "settings/cookies/"

OnConflict = Literal["skip", "overwrite"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return loads_meta(raw)
    return {}


def _collect_settings_files(user_id: int) -> dict[str, bytes]:
    from on1y.subscriptions.settings import load_subscription_settings
    from on1y.user.paths import COOKIE_PLATFORMS, user_cookie_path
    from on1y.user.profile import load_user_profile

    files: dict[str, bytes] = {}
    subscription = load_subscription_settings(user_id=user_id)
    files[SETTINGS_SUBSCRIPTION] = json.dumps(
        subscription, ensure_ascii=False, indent=2
    ).encode("utf-8")
    profile = load_user_profile(user_id=user_id, create_if_missing=False)
    fragment = {
        "kindle": profile.get("kindle") or {},
        "economist": profile.get("economist") or {},
    }
    files[SETTINGS_PROFILE] = json.dumps(fragment, ensure_ascii=False, indent=2).encode(
        "utf-8"
    )
    for platform in COOKIE_PLATFORMS:
        path = user_cookie_path(user_id, platform)
        if path.is_file():
            files[f"{SETTINGS_COOKIES_PREFIX}{platform}.json"] = path.read_bytes()
    return files


def export_user_archive(
    storage: Any,
    user_id: int,
    *,
    include_trash: bool = False,
    include_settings: bool = False,
) -> bytes:
    """Build a zip archive of feed items (not hotlist) for *user_id*."""
    conn = storage._connect()

    trash_clause = "" if include_trash else "AND r.deleted_at IS NULL"
    feed_clause = is_feed_row_sql("r")
    rows = conn.execute(
        f"""
        SELECT
            r.id,
            r.url,
            r.platform,
            r.source,
            r.raw_title,
            r.body_text,
            r.content_type,
            r.extract_status,
            r.extract_error,
            r.source_meta,
            r.ingested_at,
            r.deleted_at,
            r.theme_source,
            t.slug AS theme_slug,
            d.summary,
            d.key_points,
            d.topics,
            d.distill_status,
            d.distill_error,
            d.model,
            d.prompt_version,
            d.reader_text
        FROM raw_items r
        LEFT JOIN themes t ON t.id = r.theme_id
        LEFT JOIN distilled_items d ON d.raw_id = r.id
        WHERE r.user_id = ? AND {feed_clause} {trash_clause}
        ORDER BY r.id ASC
        """,
        (user_id,),
    ).fetchall()

    raw_ids = [int(r["id"]) for r in rows]
    tags_by_raw: dict[int, list[dict[str, Any]]] = {rid: [] for rid in raw_ids}
    if raw_ids:
        placeholders = ",".join("?" * len(raw_ids))
        tag_rows = conn.execute(
            f"""
            SELECT it.raw_id, t.name, it.confidence, it.source
            FROM item_tags it
            JOIN tags t ON t.id = it.tag_id
            WHERE it.raw_id IN ({placeholders})
            ORDER BY it.raw_id ASC, t.name ASC
            """,
            raw_ids,
        ).fetchall()
        for tr in tag_rows:
            tags_by_raw[int(tr["raw_id"])].append(
                {
                    "name": str(tr["name"]),
                    "confidence": tr["confidence"],
                    "source": str(tr["source"] or "llm"),
                }
            )

    relations_by_url: dict[str, list[dict[str, Any]]] = {}
    if raw_ids:
        rel_rows = conn.execute(
            f"""
            SELECT r1.url AS from_url, r2.url AS to_url,
                   ir.relation_type, ir.note, ir.confidence, ir.source
            FROM item_relations ir
            JOIN raw_items r1 ON r1.id = ir.from_raw_id
            JOIN raw_items r2 ON r2.id = ir.to_raw_id
            WHERE r1.user_id = ? AND r1.id IN ({placeholders})
            """,
            (user_id, *raw_ids),
        ).fetchall()
        for rr in rel_rows:
            from_url = str(rr["from_url"])
            relations_by_url.setdefault(from_url, []).append(
                {
                    "to_url": str(rr["to_url"]),
                    "relation_type": str(rr["relation_type"]),
                    "note": rr["note"],
                    "confidence": rr["confidence"],
                    "source": str(rr["source"] or "llm"),
                }
            )

    theme_slugs: set[str] = set()
    items: list[dict[str, Any]] = []
    for row in rows:
        slug = str(row["theme_slug"]) if row["theme_slug"] else None
        if slug:
            theme_slugs.add(slug)
        item: dict[str, Any] = {
            "url": str(row["url"]),
            "platform": str(row["platform"]),
            "source": str(row["source"]),
            "raw_title": row["raw_title"],
            "body_text": row["body_text"],
            "content_type": str(row["content_type"]),
            "extract_status": str(row["extract_status"]),
            "extract_error": row["extract_error"],
            "source_meta": _parse_meta(row["source_meta"]),
            "ingested_at": row["ingested_at"],
            "deleted_at": row["deleted_at"],
            "theme_slug": slug,
            "theme_source": str(row["theme_source"] or "llm"),
            "tags": tags_by_raw.get(int(row["id"]), []),
            "relations": relations_by_url.get(str(row["url"]), []),
        }
        if row["summary"] is not None or row["distill_status"]:
            item["distill"] = {
                "summary": row["summary"],
                "key_points": loads_json_list(row["key_points"]),
                "topics": loads_json_list(row["topics"]),
                "distill_status": str(row["distill_status"] or "ok"),
                "distill_error": row["distill_error"],
                "model": row["model"],
                "prompt_version": row["prompt_version"],
                "reader_text": row["reader_text"],
            }
        items.append(item)

    custom_themes: list[dict[str, Any]] = []
    if theme_slugs:
        placeholders = ",".join("?" * len(theme_slugs))
        theme_rows = conn.execute(
            f"""
            SELECT slug, name_zh, name_en, description_zh, description_en,
                   sort_order, is_builtin
            FROM themes
            WHERE slug IN ({placeholders}) AND COALESCE(is_builtin, 0) = 0
            ORDER BY sort_order ASC, id ASC
            """,
            tuple(theme_slugs),
        ).fetchall()
        custom_themes = [dict(r) for r in theme_rows]

    manifest = {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "exported_at": _utc_now(),
        "source_user_id": user_id,
        "item_count": len(items),
        "include_trash": include_trash,
        "include_settings": include_settings,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr(THEMES_NAME, json.dumps(custom_themes, ensure_ascii=False, indent=2))
        lines = "\n".join(json.dumps(item, ensure_ascii=False) for item in items)
        if lines:
            lines += "\n"
        zf.writestr(ITEMS_NAME, lines)
        if include_settings:
            for rel_path, payload in _collect_settings_files(user_id).items():
                zf.writestr(rel_path, payload)
    return buf.getvalue()


def _parse_archive_contents(
    zf: zipfile.ZipFile, names: set[str]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if MANIFEST_NAME not in names or ITEMS_NAME not in names:
        raise ValueError(f"archive must contain {MANIFEST_NAME} and {ITEMS_NAME}")
    manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    if manifest.get("format") != ARCHIVE_FORMAT:
        raise ValueError(f"unsupported archive format: {manifest.get('format')}")
    if int(manifest.get("version", 0)) != ARCHIVE_VERSION:
        raise ValueError(f"unsupported archive version: {manifest.get('version')}")
    themes: list[dict[str, Any]] = []
    if THEMES_NAME in names:
        raw_themes = json.loads(zf.read(THEMES_NAME).decode("utf-8"))
        if isinstance(raw_themes, list):
            themes = [t for t in raw_themes if isinstance(t, dict)]
    items: list[dict[str, Any]] = []
    for line in zf.read(ITEMS_NAME).decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict) and row.get("url"):
            items.append(row)
    return manifest, items, themes


def _read_archive_payload(
    data: bytes,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], zipfile.ZipFile, set[str]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("not a valid zip archive") from exc
    names = set(zf.namelist())
    manifest, items, themes = _parse_archive_contents(zf, names)
    return manifest, items, themes, zf, names


def _import_settings_bundle(
    user_id: int,
    zf: zipfile.ZipFile,
    names: set[str],
    errors: list[str],
) -> dict[str, int]:
    from on1y.cookies.import_user import persist_user_cookie_payload
    from on1y.cookies.loader import PLATFORM_COOKIE_ATTR
    from on1y.subscriptions.settings import save_subscription_settings

    stats = {"cookies_restored": 0, "subscription_restored": 0, "profile_restored": 0}
    if SETTINGS_PROFILE in names:
        try:
            from on1y.user.profile import patch_user_profile

            raw = json.loads(zf.read(SETTINGS_PROFILE).decode("utf-8"))
            if isinstance(raw, dict):
                sections: dict[str, Any] = {}
                if isinstance(raw.get("kindle"), dict):
                    sections["kindle"] = raw["kindle"]
                if isinstance(raw.get("economist"), dict):
                    sections["economist"] = raw["economist"]
                if sections:
                    patch_user_profile(user_id=user_id, **sections)
                    stats["profile_restored"] = 1
        except Exception as exc:
            errors.append(f"profile: {exc}")

    if SETTINGS_SUBSCRIPTION in names:
        try:
            raw = json.loads(zf.read(SETTINGS_SUBSCRIPTION).decode("utf-8"))
            if isinstance(raw, dict):
                save_subscription_settings(
                    bilibili_sync_since=raw.get("bilibili_sync_since"),
                    youtube_sync_since=raw.get("youtube_sync_since"),
                    zhihu_sync_since=raw.get("zhihu_sync_since"),
                    enabled_platforms=raw.get("enabled_platforms"),
                    user_id=user_id,
                )
                stats["subscription_restored"] = 1
        except Exception as exc:
            errors.append(f"subscription: {exc}")

    for platform in PLATFORM_COOKIE_ATTR:
        key = f"{SETTINGS_COOKIES_PREFIX}{platform}.json"
        if key not in names:
            continue
        try:
            data = json.loads(zf.read(key).decode("utf-8"))
            if isinstance(data, (dict, list)):
                persist_user_cookie_payload(platform, data, user_id=user_id)
                stats["cookies_restored"] += 1
        except Exception as exc:
            errors.append(f"cookie {platform}: {exc}")
    return stats


def import_user_archive(
    storage: Any,
    user_id: int,
    data: bytes,
    *,
    on_conflict: OnConflict = "overwrite",
) -> dict[str, Any]:
    """Restore archive into *user_id* (URLs are the stable keys)."""
    from on1y.utils.json_util import dumps_meta

    manifest, items, themes, zf, names = _read_archive_payload(data)
    errors: list[str] = []
    stats = {
        "imported": 0,
        "skipped": 0,
        "themes_created": 0,
        "cookies_restored": 0,
        "subscription_restored": 0,
        "profile_restored": 0,
        "errors": errors,
    }

    with user_context(user_id):
        for theme in themes:
            slug = str(theme.get("slug") or "").strip().lower()
            if not slug or storage.get_theme_id_by_slug(slug) is not None:
                continue
            try:
                storage.create_theme(
                    slug=slug,
                    name_zh=str(theme.get("name_zh") or slug),
                    name_en=str(theme.get("name_en") or theme.get("name_zh") or slug),
                    description_zh=str(theme.get("description_zh") or ""),
                    description_en=str(theme.get("description_en") or ""),
                    sort_order=int(theme["sort_order"]) if theme.get("sort_order") is not None else None,
                    is_builtin=False,
                )
                stats["themes_created"] += 1
            except Exception as exc:
                stats["errors"].append(f"theme {slug}: {exc}")

        url_to_raw_id: dict[str, int] = {}

        for item in items:
            url = str(item["url"]).strip()
            if not url:
                continue
            existing = storage.get_raw_by_url(url)
            if existing is not None and on_conflict == "skip":
                stats["skipped"] += 1
                url_to_raw_id[url] = existing.id
                continue
            try:
                raw = storage.upsert_raw_item(
                    RawItemCreate(
                        url=url,
                        platform=str(item.get("platform") or "unknown"),
                        source=SourceType(str(item.get("source") or "manual")),
                        raw_title=item.get("raw_title"),
                        body_text=item.get("body_text"),
                        content_type=ContentType(str(item.get("content_type") or "unknown")),
                        extract_status=ExtractStatus(str(item.get("extract_status") or "ok")),
                        extract_error=item.get("extract_error"),
                        source_meta=_parse_meta(item.get("source_meta")),
                    )
                )
                raw_id = raw.id
                meta = _parse_meta(item.get("source_meta"))
                deleted_at = item.get("deleted_at")
                with storage.transaction() as conn:
                    conn.execute(
                        """
                        UPDATE raw_items
                        SET source_meta = ?, deleted_at = ?, ingested_at = COALESCE(?, ingested_at)
                        WHERE id = ? AND user_id = ?
                        """,
                        (
                            dumps_meta(meta),
                            deleted_at,
                            item.get("ingested_at"),
                            raw_id,
                            user_id,
                        ),
                    )
                theme_slug = item.get("theme_slug")
                if theme_slug:
                    storage.set_item_theme_by_slug(
                        raw_id,
                        str(theme_slug),
                        source=str(item.get("theme_source") or "llm"),
                    )
                distill = item.get("distill")
                if isinstance(distill, dict):
                    storage.upsert_distilled(
                        raw_id=raw_id,
                        summary=distill.get("summary"),
                        key_points=loads_json_list(distill.get("key_points"))
                        if not isinstance(distill.get("key_points"), list)
                        else distill.get("key_points") or [],
                        topics=loads_json_list(distill.get("topics"))
                        if not isinstance(distill.get("topics"), list)
                        else distill.get("topics") or [],
                        model=distill.get("model"),
                        prompt_version=distill.get("prompt_version"),
                        status=str(distill.get("distill_status") or "ok"),
                        error=distill.get("distill_error"),
                        reader_text=distill.get("reader_text"),
                    )
                storage.clear_item_tags(raw_id)
                for tag in item.get("tags") or []:
                    if not isinstance(tag, dict):
                        continue
                    name = str(tag.get("name") or "").strip()
                    if not name:
                        continue
                    tag_id = storage.ensure_flat_tag(name)
                    storage.link_item_tag(
                        raw_id,
                        tag_id,
                        confidence=tag.get("confidence"),
                        source=str(tag.get("source") or "llm"),
                    )
                url_to_raw_id[url] = raw_id
                stats["imported"] += 1
            except Exception as exc:
                stats["errors"].append(f"{url}: {exc}")

        for item in items:
            from_url = str(item.get("url") or "").strip()
            from_id = url_to_raw_id.get(from_url)
            if from_id is None:
                continue
            for rel in item.get("relations") or []:
                if not isinstance(rel, dict):
                    continue
                to_url = str(rel.get("to_url") or "").strip()
                to_id = url_to_raw_id.get(to_url)
                if not to_id:
                    continue
                try:
                    storage.add_relation(
                        from_raw_id=from_id,
                        to_raw_id=to_id,
                        relation_type=str(rel.get("relation_type") or "related"),
                        note=rel.get("note"),
                        confidence=rel.get("confidence"),
                        source=str(rel.get("source") or "llm"),
                    )
                except Exception as exc:
                    stats["errors"].append(f"relation {from_url} -> {to_url}: {exc}")

        if manifest.get("include_settings") or any(n.startswith("settings/") for n in names):
            settings_stats = _import_settings_bundle(user_id, zf, names, errors)
            stats["cookies_restored"] = settings_stats["cookies_restored"]
            stats["subscription_restored"] = settings_stats["subscription_restored"]
            stats["profile_restored"] = settings_stats["profile_restored"]

    zf.close()

    return {
        "manifest": manifest,
        "imported": stats["imported"],
        "skipped": stats["skipped"],
        "themes_created": stats["themes_created"],
        "cookies_restored": stats["cookies_restored"],
        "subscription_restored": stats["subscription_restored"],
        "profile_restored": stats["profile_restored"],
        "errors": stats["errors"][:20],
        "error_count": len(stats["errors"]),
    }


def default_export_filename(username: str = "library") -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in username)[:32] or "library"
    return f"on1y-{safe}-{stamp}.on1y.zip"


def write_archive_to_path(storage: Any, user_id: int, path: Path, **kwargs: Any) -> dict[str, Any]:
    data = export_user_archive(storage, user_id, **kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path), "bytes": len(data)}


def read_archive_from_path(storage: Any, user_id: int, path: Path, **kwargs: Any) -> dict[str, Any]:
    return import_user_archive(storage, user_id, path.read_bytes(), **kwargs)
