"""Audio preparation on the local disk: download, convert and split in a temporary folder."""

import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from vidbrief.domain.models import AudioChunk
from vidbrief.domain.video import VideoId


class AudioDownloader(Protocol):
    """Fetches the original audio of a video into a folder."""

    def download(self, video_id: VideoId, workdir: Path) -> Path: ...


class AudioProcessor(Protocol):
    """Converts audio for speech-to-text and splits it by size."""

    def normalize(self, source: Path, destination: Path) -> None: ...

    def split(self, path: Path, max_bytes: int) -> list[Path]: ...


class LocalAudioProvider:
    """Prepare transcription-ready audio chunks inside a private temporary directory.

    Args:
        downloader: Fetches the original audio stream.
        processor: Converts and splits the audio.
        max_chunk_bytes: Upper bound for each chunk sent to speech-to-text.
    """

    def __init__(
        self,
        *,
        downloader: AudioDownloader,
        processor: AudioProcessor,
        max_chunk_bytes: int,
    ) -> None:
        self._downloader = downloader
        self._processor = processor
        self._max_chunk_bytes = max_chunk_bytes

    @contextmanager
    def prepare_audio(self, video_id: VideoId) -> Iterator[Sequence[AudioChunk]]:
        """Yield the audio chunks of ``video_id``; every file is deleted on exit.

        Raises:
            AudioProcessingError: If the audio cannot be downloaded, converted or split.
            VideoUnavailableError: If the video cannot be accessed.
            ExternalServiceError: If YouTube refuses or fails the download.
        """
        with tempfile.TemporaryDirectory(prefix="vidbrief-audio-") as tmp:
            workdir = Path(tmp)
            source = self._downloader.download(video_id, workdir)
            normalized = workdir / f"{video_id.value}.ogg"
            self._processor.normalize(source, normalized)
            # The original stream can be ~5x larger than the converted one; dropping it
            # right away keeps peak disk usage low for long videos.
            source.unlink()
            paths = self._processor.split(normalized, self._max_chunk_bytes)
            yield tuple(AudioChunk(index=index, path=path) for index, path in enumerate(paths))
