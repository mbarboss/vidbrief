"""Transcribes a real video with Groq Whisper (opt-in, needs network and GROQ_API_KEY)."""

import pytest

from vidbrief.adapters.ffmpeg_audio import FfmpegAudioProcessor
from vidbrief.adapters.groq_transcriber import GroqTranscriber
from vidbrief.adapters.local_audio import LocalAudioProvider
from vidbrief.adapters.ytdlp_audio import YtDlpAudioDownloader
from vidbrief.config import get_settings
from vidbrief.domain.models import TranscriptSource
from vidbrief.domain.video import VideoId

pytestmark = pytest.mark.integration


def test_transcribes_a_short_video() -> None:
    settings = get_settings()
    provider = LocalAudioProvider(
        downloader=YtDlpAudioDownloader(socket_timeout_seconds=30.0),
        processor=FfmpegAudioProcessor(timeout_seconds=120.0),
        max_chunk_bytes=settings.audio_chunk_max_bytes,
    )
    video_id = VideoId("jNQXAC9IVRw")

    # "Me at the zoo" is 19 seconds long, which keeps the test cheap on the free tier.
    with provider.prepare_audio(video_id) as chunks:
        transcript = GroqTranscriber.from_settings(settings).transcribe(video_id, chunks, "en")

    assert transcript.source is TranscriptSource.SPEECH_TO_TEXT
    assert transcript.language == "en"
    assert "elephant" in transcript.text.lower()
