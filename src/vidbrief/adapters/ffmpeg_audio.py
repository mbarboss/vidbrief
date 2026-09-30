"""Audio conversion and splitting with the ffmpeg command-line tools."""

import logging
import math
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from vidbrief.domain.errors import AudioProcessingError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 900.0
# Leaves room for container overhead and for segments that run slightly long, since
# ffmpeg can only cut on packet boundaries.
_CHUNK_SIZE_MARGIN = 0.9
_STDERR_TAIL_CHARS = 2000
# Only local files may be opened. Media containers and playlists can reference other
# protocols (http, tcp, concat...), which would turn a crafted file into SSRF or local
# file disclosure.
_LOCKED_DOWN_INPUT = ("-protocol_whitelist", "file")
_QUIET = ("-nostdin", "-hide_banner", "-loglevel", "error")
# Opus at 24 kbps keeps speech fully intelligible for Whisper at ~2.7 KB/s, so two hours of
# audio fit in a single 25 MB request; Whisper resamples everything to 16 kHz mono anyway.
_SPEECH_ENCODING = (
    "-ac", "1",
    "-ar", "16000",
    "-c:a", "libopus",
    "-b:a", "24k",
    "-application", "voip",
)  # fmt: skip


class CommandRunner(Protocol):
    """Runs an external program and returns its standard output."""

    def __call__(self, args: Sequence[str], *, timeout_seconds: float) -> str: ...


def run_command(args: Sequence[str], *, timeout_seconds: float) -> str:
    """Run ``args`` without a shell and return its standard output.

    Raises:
        AudioProcessingError: ``"command_timeout"`` if it runs too long, or
            ``"command_failed"`` if it cannot start or exits with an error.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, no shell, trusted binary
            list(args),
            capture_output=True,
            check=True,
            timeout=timeout_seconds,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        logger.warning("external command timed out", extra={"program": Path(args[0]).name})
        raise AudioProcessingError("command_timeout") from None
    except subprocess.CalledProcessError as error:
        logger.warning(
            "external command failed",
            extra={
                "program": Path(args[0]).name,
                "exit_code": error.returncode,
                "stderr": (error.stderr or "")[-_STDERR_TAIL_CHARS:],
            },
        )
        raise AudioProcessingError("command_failed") from None
    except OSError:
        logger.warning("external command could not start", extra={"program": Path(args[0]).name})
        raise AudioProcessingError("command_failed") from None
    return completed.stdout


class FfmpegAudioProcessor:
    """Convert audio for speech-to-text and split it into size-limited chunks.

    Args:
        ffmpeg_path: The ffmpeg executable; looked up on ``PATH`` when omitted.
        ffprobe_path: The ffprobe executable; looked up on ``PATH`` when omitted.
        runner: Executes the commands; replaceable in tests.
        timeout_seconds: Maximum run time of each ffmpeg or ffprobe call.

    Raises:
        AudioProcessingError: ``"ffmpeg_not_found"`` if ffmpeg or ffprobe is missing, so a
            misconfigured installation fails at startup rather than mid-request.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        runner: CommandRunner = run_command,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._ffmpeg = ffmpeg_path or _require_binary("ffmpeg")
        self._ffprobe = ffprobe_path or _require_binary("ffprobe")
        self._run = runner
        self._timeout_seconds = timeout_seconds

    def normalize(self, source: Path, destination: Path) -> None:
        """Write the first audio stream of ``source`` to ``destination`` as mono Opus.

        Video, subtitle and data streams and all metadata are dropped.
        """
        self._ffmpeg_run(
            *_LOCKED_DOWN_INPUT,
            "-i", _file_url(source),
            "-map", "0:a:0",
            "-vn", "-sn", "-dn",
            "-map_metadata", "-1",
            *_SPEECH_ENCODING,
            _file_url(destination),
        )  # fmt: skip

    def probe_duration(self, path: Path) -> float:
        """Return the duration of ``path`` in seconds.

        Raises:
            AudioProcessingError: ``"probe_failed"`` if no positive, finite duration is found.
        """
        output = self._run(
            [
                self._ffprobe,
                "-v", "error",
                *_LOCKED_DOWN_INPUT,
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                _file_url(path),
            ],
            timeout_seconds=self._timeout_seconds,
        )  # fmt: skip
        try:
            duration = float(output.strip())
        except ValueError:
            raise AudioProcessingError("probe_failed") from None
        if not math.isfinite(duration) or duration <= 0:
            raise AudioProcessingError("probe_failed")
        return duration

    def split(self, path: Path, max_bytes: int) -> list[Path]:
        """Return ``path`` itself if small enough, otherwise its chunks in playback order.

        Chunks are cut by time, sized from the file's average bitrate, and written next to
        ``path``.

        Raises:
            AudioProcessingError: If the limit cannot hold one second of audio, ffmpeg
                produces nothing, or a chunk still exceeds ``max_bytes``.
        """
        size = path.stat().st_size
        if size <= max_bytes:
            return [path]

        duration = self.probe_duration(path)
        segment_seconds = math.floor(duration * max_bytes * _CHUNK_SIZE_MARGIN / size)
        if segment_seconds < 1:
            raise AudioProcessingError("chunk_limit_too_small")

        pattern = path.with_name(f"{path.stem}.chunk%03d{path.suffix}")
        self._ffmpeg_run(
            *_LOCKED_DOWN_INPUT,
            "-i", _file_url(path),
            "-map", "0:a:0",
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(segment_seconds),
            "-reset_timestamps", "1",
            _file_url(pattern),
        )  # fmt: skip

        chunks = sorted(path.parent.glob(f"{path.stem}.chunk*{path.suffix}"))
        if not chunks:
            raise AudioProcessingError("split_failed")
        if any(chunk.stat().st_size > max_bytes for chunk in chunks):
            raise AudioProcessingError("chunk_too_large")
        return chunks

    def _ffmpeg_run(self, *args: str) -> None:
        # "-n" refuses to overwrite: every output path is expected to be new.
        self._run([self._ffmpeg, *_QUIET, "-n", *args], timeout_seconds=self._timeout_seconds)


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise AudioProcessingError("ffmpeg_not_found")
    return path


def _file_url(path: Path) -> str:
    # The explicit protocol stops ffmpeg from reading a name containing ":" as a URL.
    return f"file:{path}"
