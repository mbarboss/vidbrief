"""Tests for the human-readable progress text shared by the CLI and the web UI."""

import pytest

from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.services.progress_text import STAGE_LABELS, describe, describe_count


def test_every_visible_stage_has_a_label() -> None:
    assert dict(STAGE_LABELS) == {
        PipelineStage.CHECKING_VIDEO: "Checking the video",
        PipelineStage.FETCHING_CAPTIONS: "Looking for captions",
        PipelineStage.PREPARING_AUDIO: "Downloading the audio",
        PipelineStage.TRANSCRIBING: "Transcribing",
        PipelineStage.SUMMARIZING: "Writing the summary",
    }


@pytest.mark.parametrize(
    ("progress", "expected"),
    [
        (Progress(PipelineStage.CHECKING_VIDEO), None),
        (Progress(PipelineStage.TRANSCRIBING, step=2, total=3), "2/3"),
        # Summary totals are re-estimated as the token budget is learned.
        (Progress(PipelineStage.SUMMARIZING, step=2, total=5), "2/~5"),
        (Progress(PipelineStage.TRANSCRIBING, step=1), None),
    ],
)
def test_describe_count(progress: Progress, expected: str | None) -> None:
    assert describe_count(progress) == expected


@pytest.mark.parametrize(
    ("progress", "expected"),
    [
        (Progress(PipelineStage.FETCHING_CAPTIONS), "Looking for captions"),
        (Progress(PipelineStage.TRANSCRIBING, step=1, total=2), "Transcribing (1/2)"),
        (Progress(PipelineStage.SUMMARIZING, step=3, total=9), "Writing the summary (3/~9)"),
    ],
)
def test_describe(progress: Progress, expected: str) -> None:
    assert describe(progress) == expected
