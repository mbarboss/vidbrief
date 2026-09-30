"""Audio-only download backed by yt-dlp's Python API."""

from pathlib import Path

import yt_dlp
from yt_dlp.utils import YoutubeDLError

from vidbrief.adapters.ytdlp_common import (
    YoutubeDLFactory,
    base_options,
    translate_download_error,
)
from vidbrief.domain.errors import AudioProcessingError
from vidbrief.domain.video import VideoId

# Two hours of YouTube's best audio stream (Opus, ~130 kbps) is about 115 MB; the cap only
# stops something unexpected from filling the disk.
_DEFAULT_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
_PARTIAL_SUFFIX = ".part"


class YtDlpAudioDownloader:
    """Download the best audio-only stream of a video, never the video itself.

    Args:
        socket_timeout_seconds: Network timeout applied to every request yt-dlp makes.
        ydl_factory: Builds the ``YoutubeDL`` instance; replaceable in tests.
        max_download_bytes: Streams larger than this are not downloaded.
    """

    def __init__(
        self,
        *,
        socket_timeout_seconds: float,
        ydl_factory: YoutubeDLFactory = yt_dlp.YoutubeDL,
        max_download_bytes: int = _DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self._socket_timeout_seconds = socket_timeout_seconds
        self._ydl_factory = ydl_factory
        self._max_download_bytes = max_download_bytes

    def download(self, video_id: VideoId, workdir: Path) -> Path:
        """Download the audio of ``video_id`` into ``workdir`` and return the file path.

        Raises:
            AudioProcessingError: If no audio file was produced, including when the stream
                exceeds the size cap.
            VideoUnavailableError: If the video cannot be accessed.
            ExternalServiceError: If YouTube refuses or fails the download.
        """
        stem = f"{video_id.value}.source"
        options = {
            **base_options(self._socket_timeout_seconds),
            "skip_download": False,
            "format": "bestaudio",
            "max_filesize": self._max_download_bytes,
            "paths": {"home": str(workdir), "temp": str(workdir)},
            # Named after the validated ID rather than anything reported by YouTube.
            "outtmpl": {"default": f"{stem}.%(ext)s"},
        }
        try:
            with self._ydl_factory(options) as ydl:
                ydl.extract_info(video_id.canonical_url, download=True)
        except YoutubeDLError as error:
            raise translate_download_error(str(error)) from error

        files = [
            path
            for path in workdir.glob(f"{stem}.*")
            if path.is_file() and path.suffix != _PARTIAL_SUFFIX
        ]
        if len(files) != 1:
            raise AudioProcessingError("not_downloaded")
        return files[0]
