"""Runs the whole pipeline against YouTube and Groq (opt-in, needs network and GROQ_API_KEY)."""

import pytest

from vidbrief.adapters.ffmpeg_audio import FfmpegAudioProcessor
from vidbrief.adapters.groq_summarizer import GroqSummarizer
from vidbrief.adapters.groq_transcriber import GroqTranscriber
from vidbrief.adapters.local_audio import LocalAudioProvider
from vidbrief.adapters.ytdlp_audio import YtDlpAudioDownloader
from vidbrief.adapters.ytdlp_metadata import YtDlpMetadataProvider
from vidbrief.composition import build_pipeline
from vidbrief.config import get_settings
from vidbrief.domain.errors import CaptionsUnavailableError
from vidbrief.domain.models import CaptionTrack, Transcript, TranscriptSource
from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import SummaryPipeline

pytestmark = pytest.mark.integration

# "Me at the zoo" is 19 seconds long, which keeps the test cheap on the free tier.
VIDEO_ID = VideoId("jNQXAC9IVRw")


class NoCaptions:
    def fetch_captions(self, video_id: VideoId, track: CaptionTrack) -> Transcript:
        raise CaptionsUnavailableError("forced_by_test")


def test_summarizes_a_real_video() -> None:
    events: list[Progress] = []

    result = build_pipeline(get_settings()).run(VIDEO_ID, "pt-BR", on_progress=events.append)

    assert result.metadata.title == "Me at the zoo"
    assert result.summary.tldr
    assert result.summary.key_points
    assert events[-1] == Progress(PipelineStage.DONE)


def test_falls_back_to_transcribing_the_audio() -> None:
    settings = get_settings()
    pipeline = SummaryPipeline(
        metadata_provider=YtDlpMetadataProvider(socket_timeout_seconds=30.0),
        caption_provider=NoCaptions(),
        audio_provider=LocalAudioProvider(
            downloader=YtDlpAudioDownloader(socket_timeout_seconds=30.0),
            processor=FfmpegAudioProcessor(),
            max_chunk_bytes=settings.audio_chunk_max_bytes,
        ),
        transcriber=GroqTranscriber.from_settings(settings),
        summarizer=GroqSummarizer.from_settings(settings),
        max_duration_seconds=settings.max_video_duration_seconds,
    )

    result = pipeline.run(VIDEO_ID, "en")

    assert result.transcript_source is TranscriptSource.SPEECH_TO_TEXT
    assert "elephant" in f"{result.summary.tldr} {result.summary.key_points}".lower()
