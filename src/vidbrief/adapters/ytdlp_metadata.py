"""Video metadata lookup backed by yt-dlp's Python API."""

import logging
import re
from collections.abc import Callable
from typing import Any, Protocol, Self
from urllib.parse import urlsplit

import yt_dlp
from yt_dlp.utils import YoutubeDLError

from vidbrief.domain.errors import (
    ExternalServiceError,
    LiveStreamNotSupportedError,
    VidbriefError,
    VideoUnavailableError,
)
from vidbrief.domain.models import LiveStatus, VideoMetadata
from vidbrief.domain.video import VideoId

logger = logging.getLogger(__name__)
_ytdlp_logger = logging.getLogger("vidbrief.adapters.ytdlp")

_THUMBNAIL_HOST = "i.ytimg.com"
# Loose BCP 47 shape: keeps codes like "en", "pt-BR" or "en-orig" and drops pseudo-tracks
# such as "live_chat" or anything that could be mistaken for a path.
_LANGUAGE_CODE_RE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")

# yt-dlp only reports failures as English prose, so matching known phrases is the only way
# to tell them apart. Order matters: the first match wins.
_ERROR_MARKERS: tuple[tuple[str, Callable[[str], VidbriefError], str], ...] = (
    ("not a bot", ExternalServiceError, "bot_check"),
    ("private video", VideoUnavailableError, "private"),
    ("confirm your age", VideoUnavailableError, "age_restricted"),
    ("members-only", VideoUnavailableError, "members_only"),
    ("available in your country", VideoUnavailableError, "geo_blocked"),
    ("has been removed", VideoUnavailableError, "removed"),
    ("video unavailable", VideoUnavailableError, "unavailable"),
    ("video is unavailable", VideoUnavailableError, "unavailable"),
    ("live event will begin", LiveStreamNotSupportedError, "is_upcoming"),
    ("premieres in", LiveStreamNotSupportedError, "is_upcoming"),
)


class _InfoExtractor(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def extract_info(self, url: str, download: bool) -> Any: ...


YoutubeDLFactory = Callable[[dict[str, Any]], _InfoExtractor]


class _YtDlpLogger:
    """Forwards yt-dlp output into standard logging instead of stdout/stderr."""

    def debug(self, message: str) -> None:
        _ytdlp_logger.debug(message)

    def info(self, message: str) -> None:
        # yt-dlp's "info" is progress chatter, not an application-level event.
        _ytdlp_logger.debug(message)

    def warning(self, message: str) -> None:
        _ytdlp_logger.warning(message)

    def error(self, message: str) -> None:
        _ytdlp_logger.error(message)


class YtDlpMetadataProvider:
    """Fetch video metadata with yt-dlp without downloading any media.

    Args:
        socket_timeout_seconds: Network timeout applied to every request yt-dlp makes.
        ydl_factory: Builds the ``YoutubeDL`` instance; replaceable in tests.
    """

    def __init__(
        self,
        *,
        socket_timeout_seconds: float,
        ydl_factory: YoutubeDLFactory = yt_dlp.YoutubeDL,
    ) -> None:
        self._socket_timeout_seconds = socket_timeout_seconds
        self._ydl_factory = ydl_factory

    def fetch_metadata(self, video_id: VideoId) -> VideoMetadata:
        """Return the metadata for ``video_id``.

        Only the canonical URL rebuilt from the validated ID is ever passed to yt-dlp.

        Raises:
            VideoUnavailableError: If the video is private, removed or restricted.
            LiveStreamNotSupportedError: If the video is a scheduled stream or premiere.
            ExternalServiceError: If yt-dlp fails or answers for a different video.
        """
        try:
            with self._ydl_factory(self._options()) as ydl:
                info = ydl.extract_info(video_id.canonical_url, download=False)
        except YoutubeDLError as error:
            raise _translate_error(str(error)) from error

        if not isinstance(info, dict) or info.get("id") != video_id.value:
            raise ExternalServiceError("unexpected_response")
        return _to_metadata(video_id, info)

    def _options(self) -> dict[str, Any]:
        # No cookie options on purpose: restricted videos are rejected rather than accessed
        # with the user's Google session.
        return {
            "skip_download": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": False,
            "socket_timeout": self._socket_timeout_seconds,
            "logger": _YtDlpLogger(),
        }


def _translate_error(message: str) -> VidbriefError:
    lowered = message.lower()
    for marker, error_type, reason in _ERROR_MARKERS:
        if marker in lowered:
            return error_type(reason)
    return ExternalServiceError("download_failed")


def _to_metadata(video_id: VideoId, info: dict[str, Any]) -> VideoMetadata:
    title = info.get("title")
    return VideoMetadata(
        video_id=video_id,
        title=title.strip() if isinstance(title, str) else "",
        duration_seconds=_parse_duration(info.get("duration")),
        thumbnail_url=_parse_thumbnail(info.get("thumbnail")),
        live_status=_parse_live_status(info),
        caption_languages=_parse_languages(info.get("subtitles")),
        auto_caption_languages=_parse_languages(info.get("automatic_captions")),
    )


def _parse_duration(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float) or raw <= 0:
        return None
    return int(raw)


def _parse_thumbnail(raw: object) -> str | None:
    # The URL ends up in an <img> tag, so only YouTube's image CDN is trusted; this also
    # keeps the Content-Security-Policy img-src narrow.
    if not isinstance(raw, str):
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or parts.hostname != _THUMBNAIL_HOST
        or "@" in parts.netloc
        or port is not None
    ):
        return None
    return raw


def _parse_live_status(info: dict[str, Any]) -> LiveStatus:
    raw = info.get("live_status")
    if isinstance(raw, str) and raw in LiveStatus:
        return LiveStatus(raw)
    return LiveStatus.IS_LIVE if info.get("is_live") is True else LiveStatus.NOT_LIVE


def _parse_languages(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, dict):
        return ()
    return tuple(
        sorted(code for code in raw if isinstance(code, str) and _LANGUAGE_CODE_RE.fullmatch(code))
    )
