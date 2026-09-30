"""Tests for the ffmpeg audio processor: exact commands with a fake runner, then real ffmpeg."""

import json
import logging
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from vidbrief.adapters.ffmpeg_audio import FfmpegAudioProcessor, run_command
from vidbrief.domain.errors import AudioProcessingError

FFMPEG = "/usr/bin/ffmpeg"
FFPROBE = "/usr/bin/ffprobe"


class FakeRunner:
    """Records commands and answers each one through ``handler``."""

    def __init__(self, handler: Callable[[list[str]], str] = lambda args: "") -> None:
        self.handler = handler
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, args: Sequence[str], *, timeout_seconds: float) -> str:
        self.calls.append((list(args), timeout_seconds))
        return self.handler(list(args))


def _processor(runner: FakeRunner) -> FfmpegAudioProcessor:
    return FfmpegAudioProcessor(
        ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE, runner=runner, timeout_seconds=42.0
    )


class TestBinaries:
    def test_fails_fast_when_ffmpeg_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("vidbrief.adapters.ffmpeg_audio.shutil.which", lambda name: None)

        with pytest.raises(AudioProcessingError) as exc_info:
            FfmpegAudioProcessor()

        assert exc_info.value.reason == "ffmpeg_not_found"

    def test_resolves_binaries_from_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "vidbrief.adapters.ffmpeg_audio.shutil.which", lambda name: f"/opt/bin/{name}"
        )
        runner = FakeRunner(lambda args: "1.0\n")

        FfmpegAudioProcessor(runner=runner).probe_duration(Path("/work/a.ogg"))

        assert runner.calls[0][0][0] == "/opt/bin/ffprobe"


class TestCommands:
    def test_normalize_builds_a_locked_down_command(self) -> None:
        runner = FakeRunner()

        _processor(runner).normalize(Path("/work/id.source.webm"), Path("/work/id.ogg"))

        [(args, timeout)] = runner.calls
        assert timeout == 42.0
        assert args == [
            FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-protocol_whitelist",
            "file",
            "-i",
            "file:/work/id.source.webm",
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libopus",
            "-b:a",
            "24k",
            "-application",
            "voip",
            "file:/work/id.ogg",
        ]

    def test_probe_duration_reads_the_container_duration(self) -> None:
        runner = FakeRunner(lambda args: "213.056625\n")

        duration = _processor(runner).probe_duration(Path("/work/id.ogg"))

        assert duration == pytest.approx(213.056625)
        [(args, _)] = runner.calls
        assert args[0] == FFPROBE
        assert args[args.index("-protocol_whitelist") + 1] == "file"
        assert args[-1] == "file:/work/id.ogg"

    @pytest.mark.parametrize("output", ["N/A\n", "", "0\n", "-3\n", "nan\n", "inf\n"])
    def test_probe_duration_rejects_unusable_values(self, output: str) -> None:
        with pytest.raises(AudioProcessingError) as exc_info:
            _processor(FakeRunner(lambda args: output)).probe_duration(Path("/work/id.ogg"))

        assert exc_info.value.reason == "probe_failed"


class TestSplit:
    def test_keeps_a_small_file_whole(self, tmp_path: Path) -> None:
        audio = tmp_path / "id.ogg"
        audio.write_bytes(b"x" * 100)
        runner = FakeRunner()

        assert _processor(runner).split(audio, max_bytes=100) == [audio]
        assert runner.calls == []

    def test_segments_by_time_with_a_safety_margin(self, tmp_path: Path) -> None:
        audio = tmp_path / "id.ogg"
        audio.write_bytes(b"x" * 1000)

        def handler(args: list[str]) -> str:
            if args[0] == FFPROBE:
                return "100.0\n"
            for index in range(3):
                (tmp_path / f"id.chunk{index:03d}.ogg").write_bytes(b"x" * 350)
            return ""

        runner = FakeRunner(handler)

        chunks = _processor(runner).split(audio, max_bytes=400)

        assert chunks == [tmp_path / f"id.chunk{index:03d}.ogg" for index in range(3)]
        split_args = runner.calls[-1][0]
        # 100 s * (400 B * 0.9) / 1000 B = 36 s per segment.
        assert split_args[split_args.index("-segment_time") + 1] == "36"
        assert split_args[split_args.index("-f") + 1] == "segment"
        assert split_args[split_args.index("-c") + 1] == "copy"
        assert split_args[split_args.index("-protocol_whitelist") + 1] == "file"
        assert split_args[-1] == f"file:{tmp_path / 'id.chunk%03d.ogg'}"

    def test_rejects_limits_too_small_for_one_second(self, tmp_path: Path) -> None:
        audio = tmp_path / "id.ogg"
        audio.write_bytes(b"x" * 1_000_000)

        with pytest.raises(AudioProcessingError) as exc_info:
            _processor(FakeRunner(lambda args: "10.0\n")).split(audio, max_bytes=10)

        assert exc_info.value.reason == "chunk_limit_too_small"

    def test_rejects_chunks_that_still_exceed_the_limit(self, tmp_path: Path) -> None:
        audio = tmp_path / "id.ogg"
        audio.write_bytes(b"x" * 1000)

        def handler(args: list[str]) -> str:
            if args[0] == FFPROBE:
                return "100.0\n"
            (tmp_path / "id.chunk000.ogg").write_bytes(b"x" * 401)
            return ""

        with pytest.raises(AudioProcessingError) as exc_info:
            _processor(FakeRunner(handler)).split(audio, max_bytes=400)

        assert exc_info.value.reason == "chunk_too_large"

    def test_rejects_a_split_without_output(self, tmp_path: Path) -> None:
        audio = tmp_path / "id.ogg"
        audio.write_bytes(b"x" * 1000)

        runner = FakeRunner(lambda args: "100.0\n" if args[0] == FFPROBE else "")

        with pytest.raises(AudioProcessingError) as exc_info:
            _processor(runner).split(audio, max_bytes=400)

        assert exc_info.value.reason == "split_failed"


def _logged_stderr(caplog: pytest.LogCaptureFixture) -> str:
    return "".join(str(record.__dict__.get("stderr", "")) for record in caplog.records)


class TestRunCommand:
    def test_returns_standard_output(self) -> None:
        assert run_command([sys.executable, "-c", "print('ok')"], timeout_seconds=10) == "ok\n"

    def test_reports_failures_and_logs_stderr(self, caplog: pytest.LogCaptureFixture) -> None:
        script = "import sys; sys.stderr.write('boom details'); sys.exit(3)"

        with pytest.raises(AudioProcessingError) as exc_info:
            run_command([sys.executable, "-c", script], timeout_seconds=10)

        assert exc_info.value.reason == "command_failed"
        assert "boom details" in _logged_stderr(caplog)

    def test_reports_timeouts(self) -> None:
        script = "import time; time.sleep(5)"

        with pytest.raises(AudioProcessingError) as exc_info:
            run_command([sys.executable, "-c", script], timeout_seconds=0.2)

        assert exc_info.value.reason == "command_timeout"

    def test_reports_missing_executables(self, tmp_path: Path) -> None:
        with pytest.raises(AudioProcessingError) as exc_info:
            run_command([str(tmp_path / "missing-binary")], timeout_seconds=10)

        assert exc_info.value.reason == "command_failed"


requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is not installed",
)


def _ffmpeg(*args: str) -> None:
    run_command(
        [shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-v", "error", *args], timeout_seconds=60
    )


def _streams(path: Path) -> list[dict[str, object]]:
    output = run_command(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,channels:format_tags",
            "-of",
            "json",
            str(path),
        ],
        timeout_seconds=30,
    )
    document = json.loads(output)
    streams: list[dict[str, object]] = document["streams"]
    return [*streams, {"format_tags": document.get("format", {}).get("tags", {})}]


@requires_ffmpeg
class TestWithRealFfmpeg:
    @pytest.fixture
    def source(self, tmp_path: Path) -> Path:
        path = tmp_path / "id.source.mkv"
        # Noise instead of a pure tone: Opus would squeeze a sine wave to almost nothing,
        # which makes size-based splitting impossible to exercise.
        _ffmpeg(
            "-f", "lavfi", "-i", "anoisesrc=d=30:c=pink:r=44100:a=0.5",
            "-f", "lavfi", "-i", "testsrc=d=30:s=64x64:r=5",
            "-ac", "2", "-metadata", "title=private title", "-shortest",
            str(path),
        )  # fmt: skip
        return path

    @pytest.fixture
    def processor(self) -> FfmpegAudioProcessor:
        return FfmpegAudioProcessor(timeout_seconds=60.0)

    def test_normalizes_to_mono_opus_without_video_or_metadata(
        self, processor: FfmpegAudioProcessor, source: Path, tmp_path: Path
    ) -> None:
        normalized = tmp_path / "id.ogg"

        processor.normalize(source, normalized)

        [audio, tags] = _streams(normalized)
        assert audio["codec_type"] == "audio"
        assert audio["codec_name"] == "opus"
        assert audio["channels"] == 1
        assert "private title" not in json.dumps(tags)
        assert processor.probe_duration(normalized) == pytest.approx(30.0, abs=0.5)

    def test_splits_into_chunks_under_the_limit(
        self, processor: FfmpegAudioProcessor, source: Path, tmp_path: Path
    ) -> None:
        normalized = tmp_path / "id.ogg"
        processor.normalize(source, normalized)
        max_bytes = int(normalized.stat().st_size * 0.6)

        chunks = processor.split(normalized, max_bytes=max_bytes)

        assert len(chunks) >= 2
        assert all(chunk.stat().st_size <= max_bytes for chunk in chunks)
        total = sum(processor.probe_duration(chunk) for chunk in chunks)
        assert total == pytest.approx(30.0, abs=1.0)

    def test_refuses_to_follow_network_references(
        self, processor: FfmpegAudioProcessor, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        playlist = tmp_path / "id.source.m3u8"
        playlist.write_text(
            "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n#EXT-X-MEDIA-SEQUENCE:0\n"
            "#EXTINF:10.0,\nhttp://127.0.0.1:9/segment.ts\n#EXT-X-ENDLIST\n"
        )

        with caplog.at_level(logging.WARNING), pytest.raises(AudioProcessingError):
            processor.normalize(playlist, tmp_path / "id.ogg")

        # Recent ffmpeg versions already limit local playlists to "file,crypto,data"; the
        # message proves our stricter list is the one in force.
        assert "Protocol 'http' not on whitelist 'file'!" in _logged_stderr(caplog)
