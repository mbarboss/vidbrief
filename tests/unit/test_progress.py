"""Tests for pipeline progress events."""

from vidbrief.domain.progress import PipelineStage, Progress, ignore_progress


def test_stage_level_events_have_no_step_counts() -> None:
    progress = Progress(PipelineStage.CHECKING_VIDEO)

    assert progress.step is None
    assert progress.total is None
    assert progress.video is None


def test_ignore_progress_accepts_any_event() -> None:
    ignore_progress(Progress(PipelineStage.TRANSCRIBING, step=1, total=2))


def test_stage_values_are_stable_identifiers() -> None:
    assert [stage.value for stage in PipelineStage] == [
        "checking_video",
        "fetching_captions",
        "preparing_audio",
        "transcribing",
        "summarizing",
        "done",
    ]
