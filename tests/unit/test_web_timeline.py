"""Tests for the progress timeline shown on the job page."""

import pytest

from tests.unit.job_fakes import RESULT, VIDEO_ID, FakeClock
from vidbrief.domain.errors import UnexpectedError
from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.web.jobs import Job
from vidbrief.web.timeline import StageView, build_timeline, format_clock, format_seconds

CHECK = PipelineStage.CHECKING_VIDEO
CAPTIONS = PipelineStage.FETCHING_CAPTIONS
AUDIO = PipelineStage.PREPARING_AUDIO
TRANSCRIBE = PipelineStage.TRANSCRIBING
SUMMARY = PipelineStage.SUMMARIZING


def _job(*steps: tuple[PipelineStage, float]) -> tuple[Job, FakeClock]:
    """A job that entered each stage after the given number of seconds."""
    clock = FakeClock()
    job = Job("id", VIDEO_ID, "en", clock=clock)
    for stage, seconds in steps:
        job.on_progress(Progress(stage))
        clock.now += seconds
    return job, clock


def _rows(job: Job) -> list[tuple[str, str, str | None, str | None]]:
    return [
        (row.label, row.state, row.note, row.duration) for row in build_timeline(job.snapshot())
    ]


def test_a_new_job_lists_the_caption_path_as_pending() -> None:
    job, _ = _job()

    assert _rows(job) == [
        ("Checking the video", "todo", None, None),
        ("Looking for captions", "todo", None, None),
        ("Writing the summary", "todo", None, None),
    ]


def test_the_running_stage_is_current_and_finished_ones_show_their_time() -> None:
    job, _ = _job((CHECK, 0.9), (CAPTIONS, 0.6))

    assert _rows(job) == [
        ("Checking the video", "done", None, "0.9 s"),
        ("Looking for captions", "current", None, None),
        ("Writing the summary", "todo", None, None),
    ]


def test_without_a_caption_track_the_audio_steps_appear() -> None:
    job, _ = _job((CHECK, 1), (AUDIO, 4.2), (TRANSCRIBE, 0))

    assert _rows(job) == [
        ("Checking the video", "done", None, "1.0 s"),
        ("Looking for captions", "done", "None found, so we'll transcribe the audio.", None),
        ("Downloading the audio", "done", None, "4.2 s"),
        ("Transcribing", "current", None, None),
        ("Writing the summary", "todo", None, None),
    ]


def test_unusable_captions_explain_the_switch_to_audio() -> None:
    job, _ = _job((CHECK, 1), (CAPTIONS, 2), (AUDIO, 0))

    [_, captions, *_] = build_timeline(job.snapshot())

    assert captions.state == "done"
    assert captions.note == "Couldn't use them, so we'll transcribe the audio."
    assert captions.duration == "2.0 s"


def test_long_stages_show_their_count_and_progress() -> None:
    job, _ = _job((CHECK, 1), (CAPTIONS, 1), (SUMMARY, 0))
    job.on_progress(Progress(SUMMARY, step=2, total=5))

    summary = build_timeline(job.snapshot())[-1]

    assert summary == StageView(
        label="Writing the summary", state="current", count="2/~5", percent=40
    )


def test_counts_never_overflow_the_bar() -> None:
    job, _ = _job((TRANSCRIBE, 0))
    job.on_progress(Progress(TRANSCRIBE, step=4, total=3))

    transcribe = build_timeline(job.snapshot())[-2]

    assert transcribe.percent == 100


def test_a_finished_job_has_every_stage_done() -> None:
    job, _ = _job((CHECK, 1), (CAPTIONS, 1), (SUMMARY, 3))
    job.on_progress(Progress(PipelineStage.DONE))
    job.finish(RESULT)

    assert [row.state for row in build_timeline(job.snapshot())] == ["done", "done", "done"]


def test_a_failed_job_marks_the_stage_that_failed() -> None:
    job, _ = _job((CHECK, 1), (CAPTIONS, 1), (SUMMARY, 2))
    job.fail(UnexpectedError())

    assert _rows(job)[-1] == ("Writing the summary", "failed", None, None)


def test_a_job_that_failed_early_leaves_later_stages_pending() -> None:
    job, _ = _job((CHECK, 1))
    job.fail(UnexpectedError())

    assert [row.state for row in build_timeline(job.snapshot())] == ["failed", "todo", "todo"]


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.04, "0.0 s"), (0.9, "0.9 s"), (12.34, "12.3 s"), (59.94, "59.9 s"), (74.6, "1 min 15 s"),
     (3600, "60 min 0 s")],
)  # fmt: skip
def test_format_seconds(seconds: float, expected: str) -> None:
    assert format_seconds(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(None, None), (0, "0:00"), (19, "0:19"), (822, "13:42"), (3723, "1:02:03")],
)
def test_format_clock(seconds: int | None, expected: str | None) -> None:
    assert format_clock(seconds) == expected
