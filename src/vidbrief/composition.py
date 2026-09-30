"""Composition root: wires the real adapters into the summarization pipeline."""

from vidbrief.adapters.ffmpeg_audio import FfmpegAudioProcessor
from vidbrief.adapters.groq_summarizer import GroqSummarizer
from vidbrief.adapters.groq_transcriber import GroqTranscriber
from vidbrief.adapters.local_audio import LocalAudioProvider
from vidbrief.adapters.ytdlp_audio import YtDlpAudioDownloader
from vidbrief.adapters.ytdlp_captions import YtDlpCaptionProvider
from vidbrief.adapters.ytdlp_metadata import YtDlpMetadataProvider
from vidbrief.config import Settings
from vidbrief.services.pipeline import SummaryPipeline

# yt-dlp applies this to each socket read, not to a whole download, so it only needs to
# outlast a stalled connection.
_YTDLP_SOCKET_TIMEOUT_SECONDS = 30.0


def build_pipeline(settings: Settings) -> SummaryPipeline:
    """Create a pipeline backed by yt-dlp, ffmpeg and Groq.

    Raises:
        AudioProcessingError: ``"ffmpeg_not_found"`` if ffmpeg or ffprobe is missing.
    """
    return SummaryPipeline(
        metadata_provider=YtDlpMetadataProvider(
            socket_timeout_seconds=_YTDLP_SOCKET_TIMEOUT_SECONDS
        ),
        caption_provider=YtDlpCaptionProvider(socket_timeout_seconds=_YTDLP_SOCKET_TIMEOUT_SECONDS),
        audio_provider=LocalAudioProvider(
            downloader=YtDlpAudioDownloader(socket_timeout_seconds=_YTDLP_SOCKET_TIMEOUT_SECONDS),
            processor=FfmpegAudioProcessor(),
            max_chunk_bytes=settings.audio_chunk_max_bytes,
        ),
        transcriber=GroqTranscriber.from_settings(settings),
        summarizer=GroqSummarizer.from_settings(settings),
        max_duration_seconds=settings.max_video_duration_seconds,
    )
