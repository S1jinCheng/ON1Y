"""Bilibili extractor — decoupled metadata (fast) and subtitle fetch (slow)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import yt_dlp

from on1y.config import get_settings
from on1y.extract.base import BaseExtractor
from on1y.extract.subtitles import (
    build_video_body,
    collect_bilingual_subtitles,
    yt_dlp_subtitle_request_langs,
)
from on1y.extract.ytdlp_meta import video_metadata_from_info
from on1y.extract.ytdlp_util import build_ytdlp_opts, proxy_hint
from on1y.models.enums import ContentType
from on1y.models.extract import ExtractResult
from on1y.models.video_extract import VideoMetadata, VideoSubtitlePayload
from on1y.utils.platform import PLATFORM_BILIBILI, detect_platform

logger = logging.getLogger(__name__)

BILIBILI_EXTRA_LANGS = ("ai-zh", "ai-en")


def _subtitle_langs() -> list[str]:
    settings = get_settings()
    langs = yt_dlp_subtitle_request_langs(settings.ytdlp_sub_langs)
    for code in BILIBILI_EXTRA_LANGS:
        if code not in langs:
            langs.append(code)
    return langs


class BilibiliExtractor(BaseExtractor):
    @property
    def name(self) -> str:
        return PLATFORM_BILIBILI

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == PLATFORM_BILIBILI

    def extract(self, url: str) -> ExtractResult:
        meta = self.fetch_metadata(url)
        try:
            subs = self.fetch_subtitles(url)
        except Exception as exc:
            logger.warning("Bilibili subtitle fetch failed, using metadata only: %s", exc)
            return self._body_from_parts(
                title=meta.title,
                description=meta.description,
                subtitle_text="",
                langs_found=[],
            )
        return self._body_from_parts(
            title=subs.title or meta.title,
            description=subs.description or meta.description,
            subtitle_text=subs.subtitle_text,
            langs_found=subs.langs_found,
        )

    def fetch_metadata(self, url: str) -> VideoMetadata:
        settings = get_settings()
        opts = build_ytdlp_opts(
            cookie_path=settings.bilibili_cookies_path,
            ignore_no_formats_error=True,
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            msg = f"yt-dlp metadata error: {exc}. {proxy_hint()}"
            raise self._fail(url, msg, platform=PLATFORM_BILIBILI) from exc

        if not isinstance(info, dict):
            return VideoMetadata(title=None, description="")
        meta = video_metadata_from_info(info)
        if not meta.description and meta.title:
            return VideoMetadata(
                title=meta.title,
                description=str(meta.title)[:50_000],
                video_id=meta.video_id,
                uploader=meta.uploader,
                uploader_url=meta.uploader_url,
                uploader_avatar=meta.uploader_avatar,
                cover_image=meta.cover_image,
            )
        return meta

    def fetch_subtitles(self, url: str) -> VideoSubtitlePayload:
        settings = get_settings()
        langs = _subtitle_langs()
        meta = self.fetch_metadata(url)

        with tempfile.TemporaryDirectory(prefix="on1y_bili_sub_") as tmp:
            outtmpl = str(Path(tmp) / "%(id)s")
            sub_opts = build_ytdlp_opts(
                cookie_path=settings.bilibili_cookies_path,
                writesubtitles=True,
                writeautomaticsub=True,
                subtitleslangs=langs,
                subtitlesformat="vtt/srt/best",
                outtmpl=outtmpl,
                ignore_no_formats_error=True,
            )
            try:
                with yt_dlp.YoutubeDL(sub_opts) as ydl:
                    ydl.extract_info(url, download=True)
            except Exception as exc:
                msg = f"yt-dlp subtitle error: {exc}. {proxy_hint()}"
                raise self._fail(url, msg, platform=PLATFORM_BILIBILI) from exc

            subtitle_text, langs_found = collect_bilingual_subtitles(
                Path(tmp),
                lang_config=settings.ytdlp_sub_langs,
                prefer_lang=settings.content_locale,
            )
            if langs_found:
                logger.info("Bilibili subtitles for %s: %s", url, ", ".join(langs_found))

            _body, partial_reason = build_video_body(
                title=meta.title,
                subtitle_text=subtitle_text,
                description=meta.description or None,
                langs_found=langs_found,
                prefer_lang=settings.content_locale,
            )
            if not subtitle_text and not meta.description:
                raise self._fail(
                    url,
                    "No subtitles or description available",
                    platform=PLATFORM_BILIBILI,
                )
            return VideoSubtitlePayload(
                title=meta.title,
                description=meta.description,
                subtitle_text=subtitle_text,
                langs_found=langs_found,
                partial_reason=partial_reason,
            )

    def _body_from_parts(
        self,
        *,
        title: str | None,
        description: str,
        subtitle_text: str,
        langs_found: list[str],
    ) -> ExtractResult:
        body, partial_reason = build_video_body(
            title=title,
            subtitle_text=subtitle_text,
            description=description or None,
            langs_found=langs_found,
            prefer_lang=get_settings().content_locale,
        )
        if not body:
            raise self._fail(
                "",
                "No subtitles or description available",
                platform=PLATFORM_BILIBILI,
            )
        if partial_reason:
            return self._partial(
                platform=PLATFORM_BILIBILI,
                raw_title=title,
                body_text=body,
                content_type=ContentType.VIDEO,
                reason=partial_reason,
            )
        return self._ok(
            platform=PLATFORM_BILIBILI,
            raw_title=title,
            body_text=body,
            content_type=ContentType.VIDEO,
        )
