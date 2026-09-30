"""The summarization pipeline: from a video ID to a summary, captions first."""

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from vidbrief.domain.captions import select_caption_track
from vidbrief.domain.eligibility import ensure_summarizable, is_plausible_transcript
from vidbrief.domain.errors import CaptionsUnavailableError
from vidbrief.domain.languages import summary_language_name
from vidbrief.domain.models import (
    CaptionTrack,
    Summary,
    Transcript,
    TranscriptSource,
    VideoMetadata,
)
from vidbrief.domain.ports import (
    AudioProvider,
    CaptionProvider,
    Summarizer,
    Transcriber,
    VideoMetadataProvider,
)
from vidbrief.domain.progress import PipelineStage, Progress, ProgressCallback, ignore_progress
from vidbrief.domain.video import VideoId

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Everything the UI shows for a finished summary.

    ``metadata.title`` and the summary text are untrusted and must be escaped or sanitized
    wherever they are rendered.
    """

    metadata: VideoMetadata
    transcript_source: TranscriptSource
    summary: Summary


class SummaryRunner(Protocol):
    """Anything that can turn a video into a summary, such as :class:`SummaryPipeline`."""

    def run(
        self, video_id: VideoId, language: str, on_progress: ProgressCallback
    ) -> PipelineResult:
        """Summarize ``video_id`` in ``language``, reporting progress along the way."""
        ...


class SummaryPipeline:
    """Summarize a video from its captions, or from its transcribed audio when needed.

    Args:
        metadata_provider: Looks up the video before anything is downloaded.
        caption_provider: Fetches the chosen caption track.
        audio_provider: Downloads and prepares the audio when captions are not usable.
        transcriber: Turns the audio into text.
        summarizer: Writes the summary.
        max_duration_seconds: Longest video accepted.
    """

    def __init__(
        self,
        *,
        metadata_provider: VideoMetadataProvider,
        caption_provider: CaptionProvider,
        audio_provider: AudioProvider,
        transcriber: Transcriber,
        summarizer: Summarizer,
        max_duration_seconds: int,
    ) -> None:
        self._metadata_provider = metadata_provider
        self._caption_provider = caption_provider
        self._audio_provider = audio_provider
        self._transcriber = transcriber
        self._summarizer = summarizer
        self._max_duration_seconds = max_duration_seconds

    def run(
        self,
        video_id: VideoId,
        language: str,
        on_progress: ProgressCallback = ignore_progress,
    ) -> PipelineResult:
        """Summarize ``video_id`` in ``language``.

        Errors raised by ``on_progress`` are logged and ignored, so a client that stops
        listening does not abort a job that is already paid for.

        Raises:
            UnsupportedLanguageError: If ``language`` is not allowlisted; nothing is fetched.
            VidbriefError: Any failure of the pipeline steps, unchanged; the message is safe
                to show to users.
        """
        summary_language_name(language)
        stages = _StageTracker(video_id, _guarded(on_progress))

        stages.enter(PipelineStage.CHECKING_VIDEO)
        metadata = self._metadata_provider.fetch_metadata(video_id)
        ensure_summarizable(metadata, self._max_duration_seconds)

        transcript = self._transcript(metadata, stages)

        stages.enter(PipelineStage.SUMMARIZING)
        summary = self._summarizer.summarize(transcript, language, on_progress=stages.report)
        stages.enter(PipelineStage.DONE)
        return PipelineResult(
            metadata=metadata, transcript_source=transcript.source, summary=summary
        )

    def _plausible_captions(self, metadata: VideoMetadata, track: CaptionTrack) -> Transcript:
        transcript = self._caption_provider.fetch_captions(metadata.video_id, track)
        # Eligibility already guarantees a known duration.
        duration = metadata.duration_seconds or 0
        if not is_plausible_transcript(transcript.text, duration):
            # The audio is bounded by the video's length, so it is the safe source here.
            raise CaptionsUnavailableError("implausibly_long")
        return transcript

    def _transcript(self, metadata: VideoMetadata, stages: "_StageTracker") -> Transcript:
        video_id = metadata.video_id
        track = select_caption_track(metadata)
        if track is not None:
            stages.enter(PipelineStage.FETCHING_CAPTIONS)
            try:
                return self._plausible_captions(metadata, track)
            except CaptionsUnavailableError as error:
                logger.info(
                    "captions unavailable, transcribing the audio instead",
                    extra={"video_id": video_id.value, "reason": error.reason},
                )

        stages.enter(PipelineStage.PREPARING_AUDIO)
        with self._audio_provider.prepare_audio(video_id) as chunks:
            stages.enter(PipelineStage.TRANSCRIBING)
            return self._transcriber.transcribe(
                video_id, chunks, metadata.original_language, on_progress=stages.report
            )


class _StageTracker:
    """Reports stage changes and logs how long each stage took."""

    def __init__(self, video_id: VideoId, report: ProgressCallback) -> None:
        self._video_id = video_id
        self.report = report
        self._current: PipelineStage | None = None
        self._started = time.monotonic()

    def enter(self, stage: PipelineStage) -> None:
        now = time.monotonic()
        if self._current is not None:
            logger.info(
                "pipeline stage finished",
                extra={
                    "video_id": self._video_id.value,
                    "stage": self._current.value,
                    "elapsed_seconds": round(now - self._started, 2),
                },
            )
        self._current = stage
        self._started = now
        self.report(Progress(stage))


def _guarded(on_progress: ProgressCallback) -> ProgressCallback:
    def report(progress: Progress) -> None:
        try:
            on_progress(progress)
        except Exception as error:
            logger.warning(
                "progress callback failed",
                extra={"stage": progress.stage.value, "error_type": type(error).__name__},
            )

    return report
