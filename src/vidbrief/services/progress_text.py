"""Human-readable progress text, shared by the command line and the web UI."""

from collections.abc import Mapping
from types import MappingProxyType

from vidbrief.domain.progress import PipelineStage, Progress

STAGE_LABELS: Mapping[PipelineStage, str] = MappingProxyType(
    {
        PipelineStage.CHECKING_VIDEO: "Checking the video",
        PipelineStage.FETCHING_CAPTIONS: "Looking for captions",
        PipelineStage.PREPARING_AUDIO: "Downloading the audio",
        PipelineStage.TRANSCRIBING: "Transcribing",
        PipelineStage.SUMMARIZING: "Writing the summary",
    }
)


def describe_count(progress: Progress) -> str | None:
    """The ``step/total`` part of ``progress``, e.g. ``2/3``, or ``None`` without counts.

    Summary totals start with ``~`` because they are re-estimated as the token budget is
    learned.
    """
    if progress.step is None or progress.total is None:
        return None
    approx = "~" if progress.stage is PipelineStage.SUMMARIZING else ""
    return f"{progress.step}/{approx}{progress.total}"


def describe(progress: Progress) -> str:
    """The stage label plus its count, e.g. ``Transcribing (2/3)``.

    Raises:
        KeyError: For ``DONE``, which has no label.
    """
    label = STAGE_LABELS[progress.stage]
    count = describe_count(progress)
    return label if count is None else f"{label} ({count})"
