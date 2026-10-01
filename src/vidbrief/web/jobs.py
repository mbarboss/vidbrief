"""Summaries run as background jobs whose progress the web pages follow live."""

import asyncio
import logging
import secrets
import threading
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from vidbrief.domain.errors import TooManyJobsError, VidbriefError
from vidbrief.domain.models import VideoMetadata
from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import PipelineResult, SummaryRunner

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
ThreadStarter = Callable[[Callable[[], None]], None]

_DEFAULT_TTL_SECONDS = 3600.0
_DEFAULT_MAX_JOBS = 50


class JobStatus(StrEnum):
    """Where a job stands."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One pipeline stage as it happened; times come from the job's monotonic clock."""

    stage: PipelineStage
    started_at: float
    finished_at: float | None = None
    step: int | None = None
    total: int | None = None


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """An immutable view of a job, safe to read from any thread.

    ``error`` is already a user-safe message. ``video`` and ``result`` hold untrusted text
    (title, summary) that templates must escape.
    """

    job_id: str
    video_id: VideoId
    language: str
    status: JobStatus
    started_at: float
    finished_at: float | None
    stages: tuple[StageRecord, ...]
    video: VideoMetadata | None
    result: PipelineResult | None
    error: str | None
    version: int

    def elapsed_seconds(self, now: float) -> float:
        """Seconds the job took, or has taken so far when it is still running."""
        end = self.finished_at if self.finished_at is not None else now
        return end - self.started_at


class Job:
    """A summary being written in a worker thread and watched from the event loop.

    The worker calls :meth:`on_progress`, :meth:`finish` or :meth:`fail`; pages read
    :meth:`snapshot` or iterate :meth:`watch`. A lock guards the state because both sides
    run on different threads.
    """

    def __init__(self, job_id: str, video_id: VideoId, language: str, *, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._watchers: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        self._snapshot = JobSnapshot(
            job_id=job_id,
            video_id=video_id,
            language=language,
            status=JobStatus.RUNNING,
            started_at=clock(),
            finished_at=None,
            stages=(),
            video=None,
            result=None,
            error=None,
            version=0,
        )

    @property
    def job_id(self) -> str:
        """The job's unguessable identifier."""
        return self._snapshot.job_id

    @property
    def watcher_count(self) -> int:
        """How many :meth:`watch` iterators are registered."""
        with self._lock:
            return len(self._watchers)

    def snapshot(self) -> JobSnapshot:
        """The job's current state."""
        with self._lock:
            return self._snapshot

    def on_progress(self, progress: Progress) -> None:
        """Record a pipeline progress event."""
        now = self._clock()

        def apply(snapshot: JobSnapshot) -> JobSnapshot:
            if progress.video is not None:
                return replace(snapshot, video=progress.video)
            stages = list(snapshot.stages)
            current = stages[-1] if stages else None
            if progress.step is not None and current is not None:
                stages[-1] = replace(current, step=progress.step, total=progress.total)
            elif current is None or current.stage is not progress.stage:
                if current is not None and current.finished_at is None:
                    stages[-1] = replace(current, finished_at=now)
                if progress.stage is not PipelineStage.DONE:
                    stages.append(StageRecord(progress.stage, started_at=now))
            return replace(snapshot, stages=tuple(stages))

        self._update(apply)

    def finish(self, result: PipelineResult) -> None:
        """Mark the job done with its result."""
        now = self._clock()
        self._update(lambda s: replace(s, status=JobStatus.DONE, result=result, finished_at=now))

    def fail(self, message: str) -> None:
        """Mark the job failed with a message that is safe to show to users."""
        now = self._clock()
        self._update(lambda s: replace(s, status=JobStatus.FAILED, error=message, finished_at=now))

    async def watch(self) -> AsyncGenerator[JobSnapshot]:
        """Yield the current state, then each new state, until the job has finished."""
        loop = asyncio.get_running_loop()
        changed = asyncio.Event()
        watcher = (loop, changed)
        with self._lock:
            self._watchers.add(watcher)
        try:
            last_version = -1
            while True:
                changed.clear()
                snapshot = self.snapshot()
                if snapshot.version != last_version:
                    last_version = snapshot.version
                    yield snapshot
                if snapshot.status is not JobStatus.RUNNING:
                    return
                await changed.wait()
        finally:
            with self._lock:
                self._watchers.discard(watcher)

    def _update(self, apply: Callable[[JobSnapshot], JobSnapshot]) -> None:
        with self._lock:
            updated = apply(self._snapshot)
            self._snapshot = replace(updated, version=updated.version + 1)
            watchers = list(self._watchers)
        for loop, changed in watchers:
            try:
                loop.call_soon_threadsafe(changed.set)
            except RuntimeError:
                # The watcher's event loop is closed (server stopping); nobody is waiting.
                continue


class JobManager:
    """Start summaries in the background and keep their state for a while.

    At most ``max_concurrent`` jobs run at once; further requests are refused rather
    than queued, so nobody waits on a job they cannot see. Finished jobs are forgotten
    after ``ttl_seconds`` or when more than ``max_jobs`` are stored.

    Args:
        runner: The pipeline that writes the summaries.
        max_concurrent: Jobs allowed to run at the same time.
        ttl_seconds: How long a finished job stays available.
        max_jobs: Most jobs kept in memory; the oldest finished ones go first.
        clock: Monotonic time source.
        start_thread: Runs a job body in the background.
    """

    def __init__(
        self,
        runner: SummaryRunner,
        *,
        max_concurrent: int,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_jobs: int = _DEFAULT_MAX_JOBS,
        clock: Clock = time.monotonic,
        start_thread: ThreadStarter | None = None,
    ) -> None:
        self._runner = runner
        self._max_concurrent = max_concurrent
        self._ttl_seconds = ttl_seconds
        self._max_jobs = max_jobs
        self._clock = clock
        self._start_thread = start_thread or _start_daemon_thread
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def submit(self, video_id: VideoId, language: str) -> str:
        """Start summarizing ``video_id`` and return the new job's ID.

        Raises:
            TooManyJobsError: If ``max_concurrent`` jobs are already running.
        """
        with self._lock:
            self._evict()
            running = sum(job.snapshot().status is JobStatus.RUNNING for job in self._jobs.values())
            if running >= self._max_concurrent:
                raise TooManyJobsError()
            job = Job(secrets.token_urlsafe(16), video_id, language, clock=self._clock)
            self._jobs[job.job_id] = job
        logger.info("job started", extra={"job_id": job.job_id[:8], "video_id": video_id.value})
        self._start_thread(lambda: self._run(job))
        return job.job_id

    def get(self, job_id: str) -> Job | None:
        """The job with ``job_id``, or ``None`` if it never existed or has expired."""
        with self._lock:
            self._evict()
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        """Log the jobs that will be lost because the server is stopping."""
        with self._lock:
            running = [
                job for job in self._jobs.values() if job.snapshot().status is JobStatus.RUNNING
            ]
        if running:
            # Worker threads are daemons: the pipeline cannot be interrupted, so stopping
            # the server abandons them instead of waiting minutes for them to finish.
            logger.warning("jobs abandoned at shutdown", extra={"count": len(running)})

    def _run(self, job: Job) -> None:
        snapshot = job.snapshot()
        log_extra = {"job_id": job.job_id[:8], "video_id": snapshot.video_id.value}
        try:
            result = self._runner.run(
                snapshot.video_id, snapshot.language, on_progress=job.on_progress
            )
        except VidbriefError as error:
            logger.warning("job failed", extra={**log_extra, "reason": error.reason})
            job.fail(error.user_message)
        except Exception:
            logger.exception("job crashed", extra=log_extra)
            job.fail(VidbriefError("unexpected").user_message)
        else:
            logger.info("job finished", extra=log_extra)
            job.finish(result)

    def _evict(self) -> None:
        now = self._clock()
        finished = sorted(
            (
                (snapshot.finished_at, job_id)
                for job_id, job in self._jobs.items()
                if (snapshot := job.snapshot()).finished_at is not None
            ),
        )
        for finished_at, job_id in finished:
            if now - finished_at > self._ttl_seconds:
                del self._jobs[job_id]
        for _, job_id in finished:
            if len(self._jobs) <= self._max_jobs:
                break
            self._jobs.pop(job_id, None)


def _start_daemon_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="vidbrief-job", daemon=True).start()
