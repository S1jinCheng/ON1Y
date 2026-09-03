"""YouTube extractor — decoupled metadata (fast) and subtitle fetch (slow)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import yt_dlp

from on1y.config import get_settings
from on1y.cookies.loader import resolve_cookie_path
from on1y.extract.base import BaseExtractor
from on1y.extract.subtitles import build_video_body, collect_bilingual_subtitles, yt_dlp_subtitle_request_langs
from on1y.extract.ytdlp_meta import video_metadata_from_info
from on1y.extract.ytdlp_util import build_ytdlp_opts, proxy_hint
from on1y.extract.youtube_rate_limit import wait_for_youtube_subtitle_request
from on1y.models.enums import ContentType
from on1y.models.extract import ExtractResult
from on1y.models.video_extract import VideoMetadata, VideoSubtitlePayload
from on1y.utils.platform import PLATFORM_YOUTUBE, detect_platform

logger = logging.getLogger(__name__)


class YouTubeExtractor(BaseExtractor):
    @property
    def name(self) -> str:
        return PLATFORM_YOUTUBE

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == PLATFORM_YOUTUBE

    def extract(self, url: str) -> ExtractResult:
        meta = self.fetch_metadata(url)
        try:
            subs = self.fetch_subtitles(url)
        except Exception as exc:
            logger.warning("Subtitle fetch failed, using metadata only: %s", exc)
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
            cookie_path=resolve_cookie_path("youtube", settings),
            ignore_no_formats_error=True,
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            msg = f"yt-dlp metadata error: {exc}. {proxy_hint()}"
            raise self._fail(url, msg, platform=PLATFORM_YOUTUBE) from exc

        if not isinstance(info, dict):
            return VideoMetadata(title=None, description="")
        return video_metadata_from_info(info)

    def fetch_subtitles(self, url: str) -> VideoSubtitlePayload:
        settings = get_settings()
        langs = yt_dlp_subtitle_request_langs(settings.ytdlp_sub_langs)

        with tempfile.TemporaryDirectory(prefix="on1y_yt_sub_") as tmp:
            outtmpl = str(Path(tmp) / "%(id)s")
            sub_opts = build_ytdlp_opts(
                cookie_path=resolve_cookie_path("youtube", settings),
                writesubtitles=True,
                writeautomaticsub=True,
                subtitleslangs=langs,
                subtitlesformat="vtt/srt/best",
                outtmpl=outtmpl,
                ignore_no_formats_error=True,
            )
            try:
                wait_for_youtube_subtitle_request()
                with yt_dlp.YoutubeDL(sub_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
            except Exception as exc:
                msg = f"yt-dlp subtitle error: {exc}. {proxy_hint()}"
                raise self._fail(url, msg, platform=PLATFORM_YOUTUBE) from exc

            meta = video_metadata_from_info(info if isinstance(info, dict) else None)
            subtitle_text, langs_found = collect_bilingual_subtitles(
                Path(tmp),
                lang_config=settings.ytdlp_sub_langs,
                prefer_lang=settings.content_locale,
            )
            if langs_found:
                logger.info("Subtitles collected for %s: %s", url, ", ".join(langs_found))

            _body, partial_reason = build_video_body(
                title=meta.title,
                subtitle_text=subtitle_text,
                description=meta.description or None,
                langs_found=langs_found,
            )
            if not subtitle_text and not meta.description:
                raise self._fail(
                    url,
                    "No subtitles or description available.",
                    platform=PLATFORM_YOUTUBE,
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
        )
        if not body:
            raise self._fail(
                "",
                "No subtitles or description available.",
                platform=PLATFORM_YOUTUBE,
            )
        if partial_reason:
            return self._partial(
                platform=PLATFORM_YOUTUBE,
                raw_title=title,
                body_text=body,
                content_type=ContentType.VIDEO,
                reason=partial_reason,
            )
        return self._ok(
            platform=PLATFORM_YOUTUBE,
            raw_title=title,
            body_text=body,
            content_type=ContentType.VIDEO,
        )
