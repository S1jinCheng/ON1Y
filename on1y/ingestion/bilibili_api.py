"""Bilibili logged-in API helpers (favorites / nav)."""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import httpx

from on1y.config import Settings, get_settings
from on1y.cookies.loader import extract_cookie_list, load_cookie_file, resolve_cookie_path
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

BILIBILI_API = "https://api.bilibili.com"
# Dynamic types we never ingest (图文/专栏/广告等)
_SKIP_DYNAMIC_TYPES = frozenset(
    {
        "DYNAMIC_TYPE_DRAW",  # 图文
        "DYNAMIC_TYPE_ARTICLE",  # 专栏
        "DYNAMIC_TYPE_WORD",
        "DYNAMIC_TYPE_MUSIC",
        "DYNAMIC_TYPE_PGC",
        "DYNAMIC_TYPE_COMMON",
        "DYNAMIC_TYPE_LIVE",
        "DYNAMIC_TYPE_MEDIALIST",
        "DYNAMIC_TYPE_COURSES",
    }
)
_VIDEO_DYNAMIC_TYPES = frozenset({"DYNAMIC_TYPE_AV"})
_VIDEO_MAJOR_TYPES = frozenset({"MAJOR_TYPE_ARCHIVE"})
DYNAMIC_VIDEO_FEATURES = (
    "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,decorationCard,"
    "commentsNewVersion,onlyfansAssetsV2,ugcDelete,onlyfansQaCard"
)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


def _cookie_jar(cookie_path) -> dict[str, str]:
    data = load_cookie_file(cookie_path)
    cookies = extract_cookie_list(data)
    return {
        str(c["name"]): str(c["value"])
        for c in cookies
        if "bilibili.com" in str(c.get("domain", ""))
    }


def fetch_bilibili_me(
    *,
    cookie_path=None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("bilibili", settings)
    jar = _cookie_jar(path)
    if not jar.get("SESSDATA"):
        raise ConfigurationError(f"No bilibili.com SESSDATA cookie in {path}")

    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)
    try:
        assert client is not None
        response = client.get(f"{BILIBILI_API}/x/web-interface/nav")
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ConfigurationError(f"Bilibili nav failed: {payload.get('message')}")
        data = payload.get("data") or {}
        mid = str(data.get("mid") or jar.get("DedeUserID") or "").strip()
        if not mid:
            raise ConfigurationError("Bilibili cookies missing mid — may be expired")
        return {
            "mid": mid,
            "name": str(data.get("uname") or mid),
            "face": str(data.get("face") or "").strip(),
            "is_login": bool(data.get("isLogin")),
        }
    finally:
        if own_client and client is not None:
            client.close()


def fetch_bilibili_favlists(
    *,
    cookie_path=None,
    settings: Settings | None = None,
    up_mid: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Return created favorites folders as {id, title, media_count}."""
    settings = settings or get_settings()
    me = fetch_bilibili_me(cookie_path=cookie_path, settings=settings, client=client)
    mid = str(up_mid or me["mid"])

    path = cookie_path or resolve_cookie_path("bilibili", settings)
    jar = _cookie_jar(path)
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    rows: list[dict[str, Any]] = []
    try:
        assert client is not None
        response = client.get(
            f"{BILIBILI_API}/x/v3/fav/folder/created/list-all",
            params={"up_mid": mid, "type": 2},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ConfigurationError(f"Bilibili favlist list failed: {payload.get('message')}")
        for folder in payload.get("data", {}).get("list") or []:
            folder_id = folder.get("id")
            if folder_id is None:
                continue
            rows.append(
                {
                    "id": str(folder_id),
                    "title": str(folder.get("title") or folder_id),
                    "media_count": int(folder.get("media_count") or 0),
                }
            )
    finally:
        if own_client and client is not None:
            client.close()

    logger.info("Fetched %s Bilibili favlist(s) for mid=%s", len(rows), mid)
    return rows


def iter_favlist_items(
    media_id: str,
    *,
    cookie_path=None,
    settings: Settings | None = None,
    page_size: int = 40,
    client: httpx.Client | None = None,
) -> Iterator[dict[str, Any]]:
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("bilibili", settings)
    jar = _cookie_jar(path)
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    pn = 1
    try:
        assert client is not None
        while True:
            response = client.get(
                f"{BILIBILI_API}/x/v3/fav/resource/list",
                params={"media_id": media_id, "pn": pn, "ps": page_size, "order": "mtime"},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise ConfigurationError(
                    f"Bilibili favlist items failed for {media_id}: {payload.get('message')}"
                )
            data = payload.get("data") or {}
            batch = data.get("medias") or []
            for item in batch:
                if isinstance(item, dict):
                    yield item
            if not batch or not data.get("has_more"):
                break
            pn += 1
    finally:
        if own_client and client is not None:
            client.close()


def fetch_bilibili_followings(
    *,
    cookie_path=None,
    settings: Settings | None = None,
    vmid: str | None = None,
    page_size: int = 50,
    client: httpx.Client | None = None,
) -> list[dict[str, str]]:
    """Return followed UPs as {mid, uname, face?} for the logged-in user (or vmid)."""
    settings = settings or get_settings()
    me = fetch_bilibili_me(cookie_path=cookie_path, settings=settings, client=client)
    target_mid = str(vmid or me["mid"])

    path = cookie_path or resolve_cookie_path("bilibili", settings)
    jar = _cookie_jar(path)
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    pn = 1
    try:
        assert client is not None
        while True:
            response = client.get(
                f"{BILIBILI_API}/x/relation/followings",
                params={"vmid": target_mid, "pn": pn, "ps": page_size, "order_type": ""},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise ConfigurationError(
                    f"Bilibili followings failed: {payload.get('message') or payload}"
                )
            data = payload.get("data") or {}
            batch = data.get("list") or []
            if not batch:
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                mid = str(item.get("mid") or "").strip()
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                face = str(item.get("face") or "").strip()
                row: dict[str, str] = {
                    "mid": mid,
                    "uname": str(item.get("uname") or item.get("name") or mid),
                }
                if face:
                    row["face"] = face
                rows.append(row)
            total = int(data.get("total") or 0)
            if pn * page_size >= total or len(batch) < page_size:
                break
            pn += 1
    finally:
        if own_client and client is not None:
            client.close()

    logger.info("Fetched %s Bilibili following(s) for vmid=%s", len(rows), target_mid)
    return rows


def fetch_bilibili_up_face(
    up_mid: str,
    *,
    cookie_path=None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Return UP face URL for a single mid (card API)."""
    up_mid = str(up_mid or "").strip()
    if not up_mid:
        return ""
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("bilibili", settings)
    jar = _cookie_jar(path)
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)
    try:
        assert client is not None
        response = client.get(
            f"{BILIBILI_API}/x/web-interface/card",
            params={"mid": up_mid},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            return ""
        card = (payload.get("data") or {}).get("card") or {}
        return str(card.get("face") or "").strip()
    except Exception as exc:
        logger.debug("Bilibili card face lookup failed mid=%s: %s", up_mid, exc)
        return ""
    finally:
        if own_client and client is not None:
            client.close()


def iter_up_recent_videos(
    up_mid: str,
    *,
    cookie_path=None,
    settings: Settings | None = None,
    page_size: int = 30,
    max_pages: int = 1,
    since_ts: int | None = None,
    client: httpx.Client | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield recent uploads from a Bilibili UP (newest first).

    When ``since_ts`` is set, only videos published on or after that Unix timestamp
    are yielded. Pagination stops once an older video is seen.
    """
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("bilibili", settings)
    jar = _cookie_jar(path)
    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    pn = 1
    try:
        assert client is not None
        while pn <= max_pages:
            response = client.get(
                f"{BILIBILI_API}/x/space/arc/search",
                params={
                    "mid": up_mid,
                    "pn": pn,
                    "ps": page_size,
                    "order": "pubdate",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise ConfigurationError(
                    f"Bilibili UP videos failed for mid={up_mid}: {payload.get('message')}"
                )
            data = payload.get("data") or {}
            list_data = data.get("list") or {}
            batch = list_data.get("vlist") if isinstance(list_data, dict) else list_data
            if not isinstance(batch, list):
                batch = []
            if not batch:
                break
            for item in batch:
                if not isinstance(item, dict):
                    continue
                if since_ts is not None:
                    try:
                        created = int(item.get("created"))
                    except (TypeError, ValueError):
                        created = None
                    if created is not None and created < since_ts:
                        return
                yield item
            if len(batch) < page_size:
                break
            if settings.bilibili_up_poll_page_interval_seconds > 0:
                time.sleep(settings.bilibili_up_poll_page_interval_seconds)
            pn += 1
    finally:
        if own_client and client is not None:
            client.close()


def _dynamic_skip_reason(item: dict[str, Any]) -> str:
    """Classify skipped dynamic items for reporting."""
    item_type = str(item.get("type") or "")
    if item_type in _SKIP_DYNAMIC_TYPES:
        if item_type == "DYNAMIC_TYPE_DRAW":
            return "draw"
        if item_type == "DYNAMIC_TYPE_ARTICLE":
            return "article"
        return "other"
    modules = item.get("modules") or {}
    major_type = str((modules.get("module_dynamic") or {}).get("major", {}).get("type") or "")
    if major_type and major_type not in _VIDEO_MAJOR_TYPES:
        if major_type == "MAJOR_TYPE_COMMON":
            return "ad"
        if major_type == "MAJOR_TYPE_DRAW":
            return "draw"
        return "other"
    if item_type == "DYNAMIC_TYPE_FORWARD":
        return "forward_non_video"
    return "other"


def parse_dynamic_video_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Extract video upload from a following-dynamics feed item (投稿视频 only)."""
    if not isinstance(item, dict):
        return None
    item_type = str(item.get("type") or "")
    if item_type in _SKIP_DYNAMIC_TYPES:
        return None
    if item_type == "DYNAMIC_TYPE_FORWARD":
        return None
    if item_type not in _VIDEO_DYNAMIC_TYPES:
        return None

    modules = item.get("modules") or {}
    author_mod = modules.get("module_author") or {}
    dynamic_mod = modules.get("module_dynamic") or {}
    major = dynamic_mod.get("major") or {}

    if str(major.get("type") or "") not in _VIDEO_MAJOR_TYPES:
        return None

    archive = major.get("archive") or {}
    bvid = str(archive.get("bvid") or "").strip()
    if not bvid:
        return None

    up_mid = str(author_mod.get("mid") or "").strip()
    if not up_mid:
        return None

    created: int | None
    try:
        created = int(author_mod.get("pub_ts"))
    except (TypeError, ValueError):
        created = None

    duration_text = str(archive.get("duration_text") or "").strip()
    duration_sec: int | None = None
    if duration_text and duration_text.count(":") == 1:
        parts = duration_text.split(":")
        try:
            duration_sec = int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            duration_sec = None
    elif duration_text and duration_text.count(":") == 2:
        parts = duration_text.split(":")
        try:
            duration_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            duration_sec = None

    up_face = str(author_mod.get("face") or "").strip()
    parsed: dict[str, Any] = {
        "dynamic_id": str(item.get("id_str") or bvid),
        "bvid": bvid,
        "title": str(archive.get("title") or "").strip(),
        "created": created,
        "description": str(archive.get("desc") or "").strip(),
        "pic": str(archive.get("cover") or "").strip(),
        "up_mid": up_mid,
        "uname": str(author_mod.get("name") or up_mid).strip(),
        "duration_sec": duration_sec,
    }
    if up_face:
        parsed["up_face"] = up_face
    return parsed


def _space_arc_to_parsed(arc: dict[str, Any], *, up_mid: str, uname: str, up_face: str = "") -> dict[str, Any]:
    """Normalize space/arc/search row to the shape used by subscription enqueue."""
    bvid = str(arc.get("bvid") or arc.get("bv_id") or "").strip()
    created: int | None
    try:
        created = int(arc.get("created"))
    except (TypeError, ValueError):
        created = None
    duration = arc.get("length") or arc.get("duration")
    try:
        duration_sec = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_sec = None
    pic = str(arc.get("pic") or arc.get("cover") or "").strip()
    parsed: dict[str, Any] = {
        "dynamic_id": bvid,
        "bvid": bvid,
        "title": str(arc.get("title") or "").strip(),
        "created": created,
        "description": str(arc.get("description") or arc.get("desc") or "").strip(),
        "pic": pic,
        "up_mid": up_mid,
        "uname": uname,
        "duration_sec": duration_sec,
    }
    if up_face:
        parsed["up_face"] = up_face
    return parsed


def iter_following_upload_videos(
    *,
    cookie_path=None,
    settings: Settings | None = None,
    max_ups: int | None = None,
    max_pages_per_up: int = 1,
    since_ts: int | None = None,
    client: httpx.Client | None = None,
    skip_stats: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield direct video uploads from followed UPs only (no dynamics feed / 转发 / 推广)."""
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("bilibili", settings)
    own_client = client is None
    if own_client:
        jar = _cookie_jar(path)
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)
    try:
        assert client is not None
        followings = fetch_bilibili_followings(
            cookie_path=path,
            settings=settings,
            client=client,
        )
        if skip_stats is not None:
            skip_stats["followings"] = len(followings)
        limit = len(followings) if not max_ups or max_ups <= 0 else min(max_ups, len(followings))
        for index, row in enumerate(followings[:limit]):
            up_mid = str(row.get("mid") or "").strip()
            if not up_mid:
                continue
            uname = str(row.get("uname") or up_mid)
            up_face = str(row.get("face") or "").strip()
            if index > 0 and settings.bilibili_up_poll_interval_seconds > 0:
                time.sleep(settings.bilibili_up_poll_interval_seconds)
            for arc in iter_up_recent_videos(
                up_mid,
                cookie_path=path,
                settings=settings,
                max_pages=max_pages_per_up,
                since_ts=since_ts,
                client=client,
            ):
                if skip_stats is not None:
                    skip_stats["videos_seen"] = skip_stats.get("videos_seen", 0) + 1
                yield _space_arc_to_parsed(arc, up_mid=up_mid, uname=uname, up_face=up_face)
    finally:
        if own_client and client is not None:
            client.close()


def iter_dynamic_video_feed(
    *,
    cookie_path=None,
    settings: Settings | None = None,
    offset: str | None = None,
    max_pages: int = 5,
    since_ts: int | None = None,
    client: httpx.Client | None = None,
    skip_stats: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield video uploads from the logged-in user's following dynamics (type=video).

    Uses one polymer feed; non-video dynamics are filtered by parse_dynamic_video_item.
    """
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("bilibili", settings)
    own_client = client is None
    if own_client:
        jar = _cookie_jar(path)
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    page_offset = (offset or "").strip() or None
    pages = 0
    try:
        assert client is not None
        while pages < max_pages:
            params: dict[str, Any] = {
                "type": "video",
                "platform": "web",
                "features": DYNAMIC_VIDEO_FEATURES,
            }
            if page_offset:
                params["offset"] = page_offset

            response = client.get(
                f"{BILIBILI_API}/x/polymer/web-dynamic/v1/feed/all",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise ConfigurationError(
                    f"Bilibili dynamic feed failed: {payload.get('message') or payload}"
                )

            data = payload.get("data") or {}
            items = data.get("items") or []
            if not items:
                break

            hit_since_cutoff = False
            for item in items:
                if skip_stats is not None:
                    skip_stats["feed_items"] = skip_stats.get("feed_items", 0) + 1
                parsed = parse_dynamic_video_item(item)
                if parsed is None:
                    if skip_stats is not None:
                        reason = _dynamic_skip_reason(item)
                        key = f"skipped_{reason}"
                        skip_stats[key] = skip_stats.get(key, 0) + 1
                    continue
                created = parsed.get("created")
                if since_ts is not None and isinstance(created, int) and created < since_ts:
                    hit_since_cutoff = True
                    break
                yield parsed

            if hit_since_cutoff or not data.get("has_more"):
                break

            next_offset = str(data.get("offset") or "").strip()
            if not next_offset or next_offset == page_offset:
                break
            page_offset = next_offset
            pages += 1
            if pages < max_pages and settings.bilibili_dynamic_poll_page_interval_seconds > 0:
                time.sleep(settings.bilibili_dynamic_poll_page_interval_seconds)
    finally:
        if own_client and client is not None:
            client.close()
