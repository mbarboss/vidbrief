"""Tests for the summarization pipeline service."""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from vidbrief.domain.errors import (
    AudioProcessingError,
    CaptionsUnavailableError,
    ExternalServiceError,
    UnsupportedLanguageError,
    VideoTooLongError,
    VideoUnavailableError,
)
from vidbrief.domain.models import (
    AudioChunk,
    CaptionKind,
    CaptionTrack,
    LiveStatus,
    Summary,
    Transcript,
    TranscriptSource,
    VideoMetadata,
)
from vidbrief.domain.progress import PipelineStage, Progress, ProgressCallback, ignore_progress
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import PipelineResult, SummaryPipeline

VIDEO_ID = VideoId("jNQXAC9IVRw")
TITLE = "Me at the zoo"
CAPTION_TEXT = "caption words about elephants"
SPEECH_TEXT = "speech words about elephants"
METADATA = VideoMetadata(
    video_id=VIDEO_ID,
    title=TITLE,
    duration_seconds=19,
    thumbnail_url="https://i.ytimg.com/vi/jNQXAC9IVRw/hqdefault.jpg",
    live_status=LiveStatus.NOT_LIVE,
    caption_languages=("en",),
    original_language="en",
)
NO_CAPTIONS = replace(METADATA, caption_languages=(), auto_caption_languages=())


class FakeMetadataProvider:
    def __init__(self, metadata: VideoMetadata | Exception = METADATA) -> None:
        self._metadata = metadata
        self.calls: list[VideoId] = []

    def fetch_metadata(self, video_id: VideoId) -> VideoMetadata:
        self.calls.append(video_id)
        if isinstance(self._metadata, Exception):
            raise self._metadata
        return self._metadata


class FakeCaptionProvider:
    def __init__(self, error: Exception | None = None, text: str = CAPTION_TEXT) -> None:
        self._error = error
        self._text = text
        self.calls: list[tuple[VideoId, CaptionTrack]] = []

    def fetch_captions(self, video_id: VideoId, track: CaptionTrack) -> Transcript:
        self.calls.append((video_id, track))
        if self._error:
            raise self._error
        return Transcript(video_id, "en", TranscriptSource.MANUAL_CAPTIONS, self._text)


class FakeAudioProvider:
    def __init__(self, tmp_path: Path, error: Exception | None = None) -> None:
        self._tmp_path = tmp_path
        self._error = error
        self.calls: list[VideoId] = []
        self.chunks: list[AudioChunk] = []

    @contextmanager
    def prepare_audio(self, video_id: VideoId) -> Iterator[Sequence[AudioChunk]]:
        self.calls.append(video_id)
        if self._error:
            raise self._error
        self.chunks = []
        for index in range(2):
            path = self._tmp_path / f"chunk{index}.ogg"
            path.write_bytes(b"audio")
            self.chunks.append(AudioChunk(index, path))
        try:
            yield tuple(self.chunks)
        finally:
            for chunk in self.chunks:
                chunk.path.unlink()


class FakeTranscriber:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[tuple[VideoId, str | None]] = []
        self.files_existed: bool | None = None

    def transcribe(
        self,
        video_id: VideoId,
        chunks: Sequence[AudioChunk],
        language: str | None,
        on_progress: ProgressCallback = ignore_progress,
    ) -> Transcript:
        self.calls.append((video_id, language))
        self.files_existed = all(chunk.path.exists() for chunk in chunks)
        for step in range(1, len(chunks) + 1):
            on_progress(Progress(PipelineStage.TRANSCRIBING, step=step, total=len(chunks)))
        if self._error:
            raise self._error
        return Transcript(video_id, language, TranscriptSource.SPEECH_TO_TEXT, SPEECH_TEXT)


class FakeSummarizer:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[tuple[Transcript, str]] = []

    def summarize(
        self,
        transcript: Transcript,
        language: str,
        on_progress: ProgressCallback = ignore_progress,
    ) -> Summary:
        self.calls.append((transcript, language))
        on_progress(Progress(PipelineStage.SUMMARIZING, step=1, total=1))
        if self._error:
            raise self._error
        return Summary(transcript.video_id, language, "Gist.", ("Point",))


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        *,
        metadata: VideoMetadata | Exception = METADATA,
        caption_error: Exception | None = None,
        caption_text: str = CAPTION_TEXT,
        audio_error: Exception | None = None,
        transcriber_error: Exception | None = None,
        summarizer_error: Exception | None = None,
    ) -> None:
        self.metadata = FakeMetadataProvider(metadata)
        self.captions = FakeCaptionProvider(caption_error, caption_text)
        self.audio = FakeAudioProvider(tmp_path, audio_error)
        self.transcriber = FakeTranscriber(transcriber_error)
        self.summarizer = FakeSummarizer(summarizer_error)
        self.events: list[Progress] = []
        self.pipeline = SummaryPipeline(
            metadata_provider=self.metadata,
            caption_provider=self.captions,
            audio_provider=self.audio,
            transcriber=self.transcriber,
            summarizer=self.summarizer,
            max_duration_seconds=7200,
        )

    def run(self, language: str = "pt-BR") -> PipelineResult:
        return self.pipeline.run(VIDEO_ID, language, on_progress=self.events.append)

    @property
    def stages(self) -> list[PipelineStage]:
        return [event.stage for event in self.events if event.step is None and event.video is None]


class TestCaptionsPath:
    def test_summarizes_the_captions(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path)

        result = harness.run()

        assert result.metadata == METADATA
        assert result.transcript_source is TranscriptSource.MANUAL_CAPTIONS
        assert result.summary == Summary(VIDEO_ID, "pt-BR", "Gist.", ("Point",))
        assert harness.captions.calls == [(VIDEO_ID, CaptionTrack("en", CaptionKind.MANUAL))]
        [(transcript, language)] = harness.summarizer.calls
        assert transcript.text == CAPTION_TEXT
        assert language == "pt-BR"

    def test_never_touches_the_audio(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path)

        harness.run()

        assert harness.audio.calls == []
        assert harness.transcriber.calls == []

    def test_reports_the_stages_in_order(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path)

        harness.run()

        assert harness.events == [
            Progress(PipelineStage.CHECKING_VIDEO),
            Progress(PipelineStage.CHECKING_VIDEO, video=METADATA),
            Progress(PipelineStage.FETCHING_CAPTIONS),
            Progress(PipelineStage.SUMMARIZING),
            Progress(PipelineStage.SUMMARIZING, step=1, total=1),
            Progress(PipelineStage.DONE),
        ]


class TestAudioFallback:
    def test_transcribes_when_there_is_no_caption_track(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, metadata=NO_CAPTIONS)

        result = harness.run()

        assert result.transcript_source is TranscriptSource.SPEECH_TO_TEXT
        assert harness.captions.calls == []
        assert harness.transcriber.calls == [(VIDEO_ID, "en")]
        assert harness.summarizer.calls[0][0].text == SPEECH_TEXT

    def test_transcribes_when_the_captions_fail(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, caption_error=CaptionsUnavailableError("no_speech"))

        result = harness.run()

        assert result.transcript_source is TranscriptSource.SPEECH_TO_TEXT
        assert len(harness.captions.calls) == 1
        assert harness.audio.calls == [VIDEO_ID]

    def test_distrusts_captions_longer_than_the_video_could_hold(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger="vidbrief")
        # METADATA is 19 seconds long, so the one-minute allowance applies.
        harness = Harness(tmp_path, caption_text="x" * (40 * 60 + 1))

        result = harness.run()

        assert result.transcript_source is TranscriptSource.SPEECH_TO_TEXT
        assert harness.summarizer.calls[0][0].text == SPEECH_TEXT
        assert any(getattr(r, "reason", None) == "implausibly_long" for r in caplog.records)

    def test_keeps_long_but_plausible_captions(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, caption_text="x" * 40 * 60)

        result = harness.run()

        assert result.transcript_source is TranscriptSource.MANUAL_CAPTIONS
        assert harness.audio.calls == []

    def test_logs_why_it_fell_back(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="vidbrief")
        harness = Harness(tmp_path, caption_error=CaptionsUnavailableError("too_large"))

        harness.run()

        [fallback] = [r for r in caplog.records if getattr(r, "reason", None) == "too_large"]
        assert getattr(fallback, "video_id", None) == VIDEO_ID.value

    def test_transcribes_while_the_audio_files_exist(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, metadata=NO_CAPTIONS)

        harness.run()

        assert harness.transcriber.files_existed is True
        assert not any(chunk.path.exists() for chunk in harness.audio.chunks)

    def test_passes_no_language_hint_when_unknown(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, metadata=replace(NO_CAPTIONS, original_language=None))

        harness.run()

        assert harness.transcriber.calls == [(VIDEO_ID, None)]

    def test_reports_the_stages_and_transcription_steps(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, caption_error=CaptionsUnavailableError("no_speech"))

        harness.run()

        assert harness.events == [
            Progress(PipelineStage.CHECKING_VIDEO),
            Progress(PipelineStage.CHECKING_VIDEO, video=METADATA),
            Progress(PipelineStage.FETCHING_CAPTIONS),
            Progress(PipelineStage.PREPARING_AUDIO),
            Progress(PipelineStage.TRANSCRIBING),
            Progress(PipelineStage.TRANSCRIBING, step=1, total=2),
            Progress(PipelineStage.TRANSCRIBING, step=2, total=2),
            Progress(PipelineStage.SUMMARIZING),
            Progress(PipelineStage.SUMMARIZING, step=1, total=1),
            Progress(PipelineStage.DONE),
        ]

    def test_cleans_up_the_audio_when_transcription_fails(self, tmp_path: Path) -> None:
        harness = Harness(
            tmp_path, metadata=NO_CAPTIONS, transcriber_error=ExternalServiceError("x")
        )

        with pytest.raises(ExternalServiceError):
            harness.run()

        assert not any(chunk.path.exists() for chunk in harness.audio.chunks)


class TestFailures:
    def test_rejects_an_unsupported_language_before_any_lookup(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path)

        with pytest.raises(UnsupportedLanguageError):
            harness.run("Klingon")

        assert harness.metadata.calls == []
        assert harness.events == []

    def test_stops_before_fetching_anything_for_ineligible_videos(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, metadata=replace(METADATA, duration_seconds=7201))

        with pytest.raises(VideoTooLongError):
            harness.run()

        assert harness.captions.calls == []
        assert harness.audio.calls == []
        assert harness.stages == [PipelineStage.CHECKING_VIDEO]
        # Only videos that will be summarized are announced to the UI.
        assert all(event.video is None for event in harness.events)

    @pytest.mark.parametrize(
        ("options", "error_type"),
        [
            ({"metadata": VideoUnavailableError("private")}, VideoUnavailableError),
            (
                {"metadata": NO_CAPTIONS, "audio_error": AudioProcessingError("x")},
                AudioProcessingError,
            ),
            ({"summarizer_error": ExternalServiceError("x")}, ExternalServiceError),
        ],
        ids=["metadata", "audio", "summary"],
    )
    def test_domain_errors_propagate_unchanged(
        self, tmp_path: Path, options: dict[str, object], error_type: type[Exception]
    ) -> None:
        harness = Harness(tmp_path, **options)  # type: ignore[arg-type]

        with pytest.raises(error_type):
            harness.run()

        assert PipelineStage.DONE not in harness.stages

    def test_a_failing_progress_callback_does_not_stop_the_job(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="vidbrief")
        harness = Harness(tmp_path, metadata=NO_CAPTIONS)

        def broken(progress: Progress) -> None:
            raise ConnectionResetError("client went away")

        result = harness.pipeline.run(VIDEO_ID, "en", on_progress=broken)

        assert result.summary.tldr == "Gist."
        assert any(getattr(r, "error_type", None) == "ConnectionResetError" for r in caplog.records)


class TestLogging:
    def test_logs_stages_with_timings_but_no_video_content(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="vidbrief")
        harness = Harness(tmp_path, caption_error=CaptionsUnavailableError("no_speech"))

        harness.run()

        finished = [r for r in caplog.records if hasattr(r, "elapsed_seconds")]
        assert {getattr(r, "stage", None) for r in finished} >= {
            "checking_video",
            "transcribing",
            "summarizing",
        }
        for record in caplog.records:
            rendered = f"{record.getMessage()} {record.__dict__}"
            for content in (TITLE, CAPTION_TEXT, SPEECH_TEXT, "Gist."):
                assert content not in rendered
