"""Progress events emitted while a video goes through the summarization pipeline."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class PipelineStage(StrEnum):
    """The steps of the pipeline, in the order they can happen."""

    CHECKING_VIDEO = "checking_video"
    FETCHING_CAPTIONS = "fetching_captions"
    PREPARING_AUDIO = "preparing_audio"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class Progress:
    """One progress update.

    A stage starts with an event without counts; long stages may follow up with
    ``step`` of ``total`` events. For summaries ``total`` is an estimate that can change
    between events.
    """

    stage: PipelineStage
    step: int | None = None
    total: int | None = None


ProgressCallback = Callable[[Progress], None]


def ignore_progress(progress: Progress) -> None:
    """Discard ``progress``; the default for callers that do not track progress."""
