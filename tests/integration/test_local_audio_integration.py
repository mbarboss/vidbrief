"""Checks the full audio fallback against YouTube and the local ffmpeg (opt-in, needs network)."""

import pytest

from vidbrief.adapters.ffmpeg_audio import FfmpegAudioProcessor
from vidbrief.adapters.local_audio import LocalAudioProvider
from vidbrief.adapters.ytdlp_audio import YtDlpAudioDownloader
from vidbrief.domain.video import VideoId

pytestmark = pytest.mark.integration


def test_prepares_transcription_ready_audio_and_cleans_up() -> None:
    processor = FfmpegAudioProcessor(timeout_seconds=120.0)
    provider = LocalAudioProvider(
        downloader=YtDlpAudioDownloader(socket_timeout_seconds=30.0),
        processor=processor,
        max_chunk_bytes=24_000_000,
    )

    # "Me at the zoo" is 19 seconds long, so it always fits in a single chunk.
    with provider.prepare_audio(VideoId("jNQXAC9IVRw")) as chunks:
        [chunk] = chunks
        assert chunk.path.suffix == ".ogg"
        assert processor.probe_duration(chunk.path) == pytest.approx(19.0, abs=1.5)
        assert [path.name for path in chunk.path.parent.iterdir()] == [chunk.path.name]
        workdir = chunk.path.parent

    assert not workdir.exists()
