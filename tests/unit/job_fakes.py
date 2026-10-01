"""Test doubles for background jobs, shared by the job and web route tests."""

import threading
from collections.abc import Callable

from vidbrief.domain.models import LiveStatus, Summary, TranscriptSource, VideoMetadata
from vidbrief.domain.progress import PipelineStage, Progress, ProgressCallback
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import PipelineResult

VIDEO_ID = VideoId("jNQXAC9IVRw")
METADATA = VideoMetadata(VIDEO_ID, "Me at the zoo", 19, None, LiveStatus.NOT_LIVE)
RESULT = PipelineResult(
    metadata=METADATA,
    transcript_source=TranscriptSource.MANUAL_CAPTIONS,
    summary=Summary(VIDEO_ID, "en", "Gist.", ("Point",)),
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class ScriptedRunner:
    """Replays progress events, optionally pausing until the test releases it."""

    def __init__(
        self,
        events: list[Progress] | None = None,
        outcome: PipelineResult | BaseException = RESULT,
        gate: threading.Event | None = None,
    ) -> None:
        self.events = events or [Progress(PipelineStage.CHECKING_VIDEO)]
        self.outcome = outcome
        self.gate = gate
        self.calls: list[tuple[VideoId, str]] = []

    def run(
        self, video_id: VideoId, language: str, on_progress: ProgressCallback
    ) -> PipelineResult:
        self.calls.append((video_id, language))
        for event in self.events:
            on_progress(event)
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def run_inline(target: Callable[[], None]) -> None:
    target()


class HeldThreads:
    """Collects job bodies instead of running them, so jobs stay "running"."""

    def __init__(self) -> None:
        self.targets: list[Callable[[], None]] = []

    def __call__(self, target: Callable[[], None]) -> None:
        self.targets.append(target)
