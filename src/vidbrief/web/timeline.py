"""Turn a job's recorded stages into the rows of the progress timeline."""

from dataclasses import dataclass
from typing import Literal

from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.services.progress_text import STAGE_LABELS, describe_count
from vidbrief.web.jobs import JobSnapshot, JobStatus, StageRecord

StageState = Literal["done", "current", "failed", "todo"]

_NO_CAPTIONS_NOTE = "None found, so we'll transcribe the audio."
_UNUSABLE_CAPTIONS_NOTE = "Couldn't use them, so we'll transcribe the audio."
_AUDIO_STAGES = (PipelineStage.PREPARING_AUDIO, PipelineStage.TRANSCRIBING)


@dataclass(frozen=True, slots=True)
class StageView:
    """One timeline row, ready for the template."""

    label: str
    state: StageState
    note: str | None = None
    duration: str | None = None
    count: str | None = None
    percent: int | None = None


def build_timeline(snapshot: JobSnapshot) -> tuple[StageView, ...]:
    """The rows to show for ``snapshot``.

    The audio rows only appear once the pipeline falls back to the audio, and the caption
    row then says why, so the timeline never lists work that will not happen.
    """
    records = {record.stage: record for record in snapshot.stages}
    uses_audio = any(stage in records for stage in _AUDIO_STAGES)
    stages = [PipelineStage.CHECKING_VIDEO, PipelineStage.FETCHING_CAPTIONS]
    if uses_audio:
        stages += _AUDIO_STAGES
    stages.append(PipelineStage.SUMMARIZING)

    rows = []
    for stage in stages:
        record = records.get(stage)
        if record is not None:
            row = _row_for(record, snapshot.status)
        elif stage is PipelineStage.FETCHING_CAPTIONS and uses_audio:
            row = StageView(STAGE_LABELS[stage], "done")
        else:
            row = StageView(STAGE_LABELS[stage], "todo")
        if stage is PipelineStage.FETCHING_CAPTIONS and uses_audio:
            note = _UNUSABLE_CAPTIONS_NOTE if record is not None else _NO_CAPTIONS_NOTE
            row = StageView(row.label, row.state, note=note, duration=row.duration)
        rows.append(row)
    return tuple(rows)


def format_seconds(seconds: float) -> str:
    """A short duration such as ``0.9 s`` or ``1 min 15 s``."""
    if round(seconds, 1) < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest} s"


def format_clock(seconds: int | None) -> str | None:
    """A video length as players show it, e.g. ``0:19``, ``13:42`` or ``1:02:03``."""
    if seconds is None:
        return None
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _row_for(record: StageRecord, status: JobStatus) -> StageView:
    label = STAGE_LABELS[record.stage]
    if record.finished_at is not None:
        return StageView(
            label, "done", duration=format_seconds(record.finished_at - record.started_at)
        )
    if status is JobStatus.FAILED:
        return StageView(label, "failed")
    count = describe_count(Progress(record.stage, step=record.step, total=record.total))
    percent = None
    if record.step is not None and record.total:
        percent = min(100, record.step * 100 // record.total)
    return StageView(label, "current", count=count, percent=percent)
