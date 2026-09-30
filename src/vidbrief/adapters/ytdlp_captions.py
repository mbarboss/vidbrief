"""Caption download backed by yt-dlp's Python API."""

import re
import tempfile
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import YoutubeDLError

from vidbrief.adapters.json3_captions import parse_json3
from vidbrief.adapters.ytdlp_common import YoutubeDLFactory, base_options
from vidbrief.domain.errors import CaptionsUnavailableError
from vidbrief.domain.models import CaptionKind, CaptionTrack, Transcript, TranscriptSource
from vidbrief.domain.video import VideoId

_CAPTION_FORMAT = "json3"
# Two hours of automatic captions take roughly 1-3 MB; anything far larger is not a
# caption file worth loading into memory.
_DEFAULT_MAX_CAPTION_BYTES = 10 * 1024 * 1024
_SOURCES = {
    CaptionKind.MANUAL: TranscriptSource.MANUAL_CAPTIONS,
    CaptionKind.AUTO: TranscriptSource.AUTO_CAPTIONS,
}


class YtDlpCaptionProvider:
    """Download a single caption track with yt-dlp and turn it into a transcript.

    Files only ever live in a private temporary directory that is removed before returning.

    Args:
        socket_timeout_seconds: Network timeout applied to every request yt-dlp makes.
        ydl_factory: Builds the ``YoutubeDL`` instance; replaceable in tests.
        max_caption_bytes: Caption files larger than this are rejected unread.
    """

    def __init__(
        self,
        *,
        socket_timeout_seconds: float,
        ydl_factory: YoutubeDLFactory = yt_dlp.YoutubeDL,
        max_caption_bytes: int = _DEFAULT_MAX_CAPTION_BYTES,
    ) -> None:
        self._socket_timeout_seconds = socket_timeout_seconds
        self._ydl_factory = ydl_factory
        self._max_caption_bytes = max_caption_bytes

    def fetch_captions(self, video_id: VideoId, track: CaptionTrack) -> Transcript:
        """Return the transcript built from ``track``.

        Raises:
            CaptionsUnavailableError: If the track cannot be downloaded, is too large,
                malformed or contains no speech.
        """
        with tempfile.TemporaryDirectory(prefix="vidbrief-captions-") as workdir:
            self._download(video_id, track, Path(workdir))
            raw = self._read_caption_file(Path(workdir))
        return Transcript(
            video_id=video_id,
            language=track.content_language,
            source=_SOURCES[track.kind],
            text=parse_json3(raw),
        )

    def _download(self, video_id: VideoId, track: CaptionTrack, workdir: Path) -> None:
        try:
            with self._ydl_factory(self._options(video_id, track, workdir)) as ydl:
                ydl.extract_info(video_id.canonical_url, download=True)
        except YoutubeDLError as error:
            raise CaptionsUnavailableError("download_failed") from error

    def _options(self, video_id: VideoId, track: CaptionTrack, workdir: Path) -> dict[str, Any]:
        return {
            **base_options(self._socket_timeout_seconds),
            "writesubtitles": track.kind is CaptionKind.MANUAL,
            "writeautomaticsub": track.kind is CaptionKind.AUTO,
            # yt-dlp reads each entry as a regex and gives bare keywords such as "all" a
            # special meaning; the anchored, escaped form matches this one code only.
            "subtitleslangs": [f"^{re.escape(track.language)}"],
            "subtitlesformat": _CAPTION_FORMAT,
            "paths": {"home": str(workdir), "temp": str(workdir)},
            # Named after the validated ID rather than anything reported by YouTube.
            "outtmpl": {"default": f"{video_id.value}.%(ext)s"},
        }

    def _read_caption_file(self, workdir: Path) -> bytes:
        files = list(workdir.glob(f"*.{_CAPTION_FORMAT}"))
        if len(files) != 1:
            raise CaptionsUnavailableError("not_downloaded")
        [caption_file] = files
        if caption_file.stat().st_size > self._max_caption_bytes:
            raise CaptionsUnavailableError("too_large")
        return caption_file.read_bytes()
