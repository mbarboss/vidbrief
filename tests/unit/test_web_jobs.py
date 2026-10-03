"""Tests for background summary jobs."""

import asyncio
import logging
import threading
from collections.abc import Callable

import pytest

from tests.unit.job_fakes import (
    METADATA,
    RESULT,
    VIDEO_ID,
    FakeClock,
    HeldThreads,
    ScriptedRunner,
    run_inline,
)
from vidbrief.domain.errors import TooManyJobsError, VideoTooLongError
from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.web.jobs import Job, JobManager, JobSnapshot, JobStatus, StageRecord


def _manager(
    runner: ScriptedRunner | None = None,
    *,
    start: Callable[[Callable[[], None]], None] = run_inline,
    clock: FakeClock | None = None,
    max_concurrent: int = 1,
    max_jobs: int = 50,
) -> JobManager:
    return JobManager(
        runner or ScriptedRunner(),
        max_concurrent=max_concurrent,
        max_jobs=max_jobs,
        clock=clock or FakeClock(),
        start_thread=start,
    )


class TestJobTimeline:
    def test_records_each_stage_with_its_timing(self) -> None:
        clock = FakeClock()
        job = Job("id", VIDEO_ID, "en", clock=clock)

        job.on_progress(Progress(PipelineStage.CHECKING_VIDEO))
        clock.now += 1.5
        job.on_progress(Progress(PipelineStage.FETCHING_CAPTIONS))
        clock.now += 0.5
        job.on_progress(Progress(PipelineStage.SUMMARIZING))

        assert job.snapshot().stages == (
            StageRecord(PipelineStage.CHECKING_VIDEO, started_at=100.0, finished_at=101.5),
            StageRecord(PipelineStage.FETCHING_CAPTIONS, started_at=101.5, finished_at=102.0),
            StageRecord(PipelineStage.SUMMARIZING, started_at=102.0),
        )

    def test_step_events_update_the_current_stage(self) -> None:
        job = Job("id", VIDEO_ID, "en", clock=FakeClock())

        job.on_progress(Progress(PipelineStage.TRANSCRIBING))
        job.on_progress(Progress(PipelineStage.TRANSCRIBING, step=1, total=3))
        job.on_progress(Progress(PipelineStage.TRANSCRIBING, step=2, total=3))

        [stage] = job.snapshot().stages
        assert (stage.step, stage.total) == (2, 3)

    def test_a_repeated_stage_start_keeps_the_running_stage(self) -> None:
        clock = FakeClock()
        job = Job("id", VIDEO_ID, "en", clock=clock)
        job.on_progress(Progress(PipelineStage.SUMMARIZING))
        clock.now += 1

        job.on_progress(Progress(PipelineStage.SUMMARIZING))

        assert job.snapshot().stages == (StageRecord(PipelineStage.SUMMARIZING, started_at=100.0),)

    def test_keeps_the_video_metadata_without_adding_a_stage(self) -> None:
        job = Job("id", VIDEO_ID, "en", clock=FakeClock())

        job.on_progress(Progress(PipelineStage.CHECKING_VIDEO))
        job.on_progress(Progress(PipelineStage.CHECKING_VIDEO, video=METADATA))

        snapshot = job.snapshot()
        assert snapshot.video == METADATA
        assert [s.stage for s in snapshot.stages] == [PipelineStage.CHECKING_VIDEO]

    def test_done_closes_the_last_stage_and_finishing_stores_the_result(self) -> None:
        clock = FakeClock()
        job = Job("id", VIDEO_ID, "en", clock=clock)
        job.on_progress(Progress(PipelineStage.SUMMARIZING))
        clock.now += 3
        job.on_progress(Progress(PipelineStage.DONE))

        job.finish(RESULT)

        snapshot = job.snapshot()
        assert snapshot.status is JobStatus.DONE
        assert snapshot.result == RESULT
        assert snapshot.stages[-1].finished_at == 103.0
        assert snapshot.finished_at == 103.0
        assert snapshot.elapsed_seconds(clock()) == 3.0

    def test_failing_keeps_the_stage_that_was_running(self) -> None:
        clock = FakeClock()
        job = Job("id", VIDEO_ID, "en", clock=clock)
        job.on_progress(Progress(PipelineStage.TRANSCRIBING))
        clock.now += 2

        job.fail("Something went wrong.")

        snapshot = job.snapshot()
        assert snapshot.status is JobStatus.FAILED
        assert snapshot.error == "Something went wrong."
        assert snapshot.stages[-1].finished_at is None
        assert snapshot.finished_at == 102.0

    def test_running_jobs_report_elapsed_time_up_to_now(self) -> None:
        clock = FakeClock()
        job = Job("id", VIDEO_ID, "en", clock=clock)

        clock.now += 7

        assert job.snapshot().elapsed_seconds(clock()) == 7.0

    def test_every_change_bumps_the_version(self) -> None:
        job = Job("id", VIDEO_ID, "en", clock=FakeClock())

        job.on_progress(Progress(PipelineStage.CHECKING_VIDEO))
        job.on_progress(Progress(PipelineStage.CHECKING_VIDEO, video=METADATA))
        job.finish(RESULT)

        assert job.snapshot().version == 3


class TestWatch:
    def test_yields_the_current_state_then_each_change_until_finished(self) -> None:
        job = Job("id", VIDEO_ID, "en", clock=FakeClock())

        async def scenario() -> list[tuple[int, JobStatus]]:
            seen: list[tuple[int, JobStatus]] = []

            async def consume() -> None:
                async for snapshot in job.watch():
                    seen.append((snapshot.version, snapshot.status))

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.01)
            await asyncio.to_thread(job.on_progress, Progress(PipelineStage.CHECKING_VIDEO))
            await asyncio.sleep(0.01)
            await asyncio.to_thread(job.finish, RESULT)
            await asyncio.wait_for(task, timeout=2)
            return seen

        assert asyncio.run(scenario()) == [
            (0, JobStatus.RUNNING),
            (1, JobStatus.RUNNING),
            (2, JobStatus.DONE),
        ]

    def test_a_state_already_seen_is_not_yielded_twice(self) -> None:
        class RacyJob(Job):
            """Changes right after the watcher cleared its signal, like a worker thread."""

            race = True

            def snapshot(self) -> JobSnapshot:
                if self.race:
                    self.race = False
                    self.on_progress(Progress(PipelineStage.CHECKING_VIDEO))
                return super().snapshot()

        job = RacyJob("id", VIDEO_ID, "en", clock=FakeClock())

        async def scenario() -> list[int]:
            versions: list[int] = []

            async def consume() -> None:
                async for snapshot in job.watch():
                    versions.append(snapshot.version)

            task = asyncio.create_task(consume())
            await asyncio.sleep(0.01)
            await asyncio.to_thread(job.finish, RESULT)
            await asyncio.wait_for(task, timeout=2)
            return versions

        assert asyncio.run(scenario()) == [1, 2]

    def test_a_finished_job_yields_once(self) -> None:
        job = Job("id", VIDEO_ID, "en", clock=FakeClock())
        job.fail("Nope.")

        async def scenario() -> list[JobStatus]:
            return [snapshot.status async for snapshot in job.watch()]

        assert asyncio.run(scenario()) == [JobStatus.FAILED]

    def test_stopped_watchers_are_forgotten(self) -> None:
        job = Job("id", VIDEO_ID, "en", clock=FakeClock())

        async def scenario() -> None:
            watcher = job.watch()
            await anext(watcher)
            await watcher.aclose()

        asyncio.run(scenario())

        assert job.watcher_count == 0

    def test_updates_after_the_watchers_loop_closed_are_ignored(self) -> None:
        job = Job("id", VIDEO_ID, "en", clock=FakeClock())
        loop = asyncio.new_event_loop()
        watcher = job.watch()
        loop.run_until_complete(anext(watcher))
        # Closing without shutting down async generators leaves the watcher registered, as
        # when the server stops while a client is still connected.
        loop.close()

        job.on_progress(Progress(PipelineStage.CHECKING_VIDEO))

        assert job.snapshot().version == 1
        assert job.watcher_count == 1


class TestJobManager:
    def test_runs_the_pipeline_and_keeps_the_result(self) -> None:
        runner = ScriptedRunner()
        manager = _manager(runner)

        job_id = manager.submit(VIDEO_ID, "en")

        job = manager.get(job_id)
        assert job is not None
        assert job.snapshot().status is JobStatus.DONE
        assert job.snapshot().result == RESULT
        assert runner.calls == [(VIDEO_ID, "en")]

    def test_job_ids_are_unguessable(self) -> None:
        manager = _manager(max_concurrent=4)

        ids = {manager.submit(VIDEO_ID, "en") for _ in range(4)}

        assert len(ids) == 4
        assert all(len(job_id) >= 22 for job_id in ids)

    def test_unknown_ids_return_none(self) -> None:
        assert _manager().get("missing") is None

    def test_pipeline_errors_fail_the_job_with_the_safe_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = _manager(ScriptedRunner(outcome=VideoTooLongError(7200)))

        with caplog.at_level(logging.WARNING, logger="vidbrief.web.jobs"):
            job_id = manager.submit(VIDEO_ID, "en")

        snapshot = manager.get(job_id).snapshot()  # type: ignore[union-attr]
        assert snapshot.status is JobStatus.FAILED
        assert snapshot.error == "This video is longer than 2 hours, the most vidbrief summarizes."
        [record] = caplog.records
        assert record.reason == "too_long"  # type: ignore[attr-defined]

    def test_unexpected_errors_fail_the_job_with_a_generic_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = _manager(ScriptedRunner(outcome=RuntimeError("internal detail")))

        with caplog.at_level(logging.ERROR, logger="vidbrief.web.jobs"):
            job_id = manager.submit(VIDEO_ID, "en")

        snapshot = manager.get(job_id).snapshot()  # type: ignore[union-attr]
        assert snapshot.error == "Something unexpected went wrong."
        assert "internal detail" not in (snapshot.error or "")
        assert caplog.records[0].exc_info is not None

    def test_refuses_new_jobs_beyond_the_concurrency_limit(self) -> None:
        threads = HeldThreads()
        manager = _manager(start=threads, max_concurrent=2)
        manager.submit(VIDEO_ID, "en")
        manager.submit(VIDEO_ID, "en")

        with pytest.raises(TooManyJobsError) as caught:
            manager.submit(VIDEO_ID, "en")

        assert caught.value.reason == "too_many_jobs"
        assert caught.value.user_message == (
            "Another summary is still running. Try again when it finishes."
        )

    def test_finished_jobs_free_their_slot(self) -> None:
        threads = HeldThreads()
        manager = _manager(start=threads)
        manager.submit(VIDEO_ID, "en")
        threads.targets[0]()

        manager.submit(VIDEO_ID, "en")

        assert len(threads.targets) == 2

    def test_finished_jobs_expire_after_the_ttl(self) -> None:
        clock = FakeClock()
        manager = _manager(clock=clock)
        old = manager.submit(VIDEO_ID, "en")

        clock.now += 3601

        assert manager.get(old) is None

    def test_finished_jobs_are_kept_within_the_ttl(self) -> None:
        clock = FakeClock()
        manager = _manager(clock=clock)
        job_id = manager.submit(VIDEO_ID, "en")

        clock.now += 3599

        assert manager.get(job_id) is not None

    def test_running_jobs_never_expire(self) -> None:
        clock = FakeClock()
        manager = _manager(start=HeldThreads(), clock=clock)
        job_id = manager.submit(VIDEO_ID, "en")

        clock.now += 99999

        assert manager.get(job_id) is not None

    def test_keeps_at_most_max_jobs_dropping_the_oldest_finished(self) -> None:
        clock = FakeClock()
        manager = _manager(clock=clock, max_jobs=2)
        first = manager.submit(VIDEO_ID, "en")
        clock.now += 1
        second = manager.submit(VIDEO_ID, "en")
        clock.now += 1
        third = manager.submit(VIDEO_ID, "en")

        assert manager.get(first) is None
        assert manager.get(second) is not None
        assert manager.get(third) is not None

    def test_shutdown_logs_abandoned_jobs(self, caplog: pytest.LogCaptureFixture) -> None:
        manager = _manager(start=HeldThreads())
        manager.submit(VIDEO_ID, "en")

        with caplog.at_level(logging.WARNING, logger="vidbrief.web.jobs"):
            manager.shutdown()

        [record] = caplog.records
        assert record.message == "jobs abandoned at shutdown"
        assert record.count == 1  # type: ignore[attr-defined]

    def test_shutdown_is_quiet_without_running_jobs(self, caplog: pytest.LogCaptureFixture) -> None:
        manager = _manager()
        manager.submit(VIDEO_ID, "en")

        with caplog.at_level(logging.WARNING, logger="vidbrief.web.jobs"):
            manager.shutdown()

        assert caplog.records == []

    def test_real_threads_run_in_the_background(self) -> None:
        gate = threading.Event()
        manager = JobManager(ScriptedRunner(gate=gate), max_concurrent=1)
        job_id = manager.submit(VIDEO_ID, "en")
        job = manager.get(job_id)
        assert job is not None
        assert job.snapshot().status is JobStatus.RUNNING

        gate.set()

        async def wait_done() -> JobStatus:
            statuses = [snapshot.status async for snapshot in job.watch()]
            return statuses[-1]

        assert asyncio.run(asyncio.wait_for(wait_done(), timeout=5)) is JobStatus.DONE
