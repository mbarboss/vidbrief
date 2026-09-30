"""Tests for the command-line entry point."""

import io
import os
import runpy
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

import pytest

from vidbrief import cli
from vidbrief.cli import main
from vidbrief.config import LogLevel, Settings
from vidbrief.domain.errors import MissingDependencyError, VideoTooLongError
from vidbrief.domain.models import LiveStatus, Summary, TranscriptSource, VideoMetadata
from vidbrief.domain.progress import PipelineStage, Progress, ProgressCallback
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import PipelineResult
from vidbrief.services.report import to_markdown

FAKE_API_KEY = "gsk_test_not_a_real_key"  # pragma: allowlist secret
URL = "https://youtu.be/jNQXAC9IVRw"
VIDEO_ID = VideoId("jNQXAC9IVRw")
RESULT = PipelineResult(
    metadata=VideoMetadata(VIDEO_ID, "Me at the zoo", 19, None, LiveStatus.NOT_LIVE),
    transcript_source=TranscriptSource.MANUAL_CAPTIONS,
    summary=Summary(VIDEO_ID, "pt-BR", "Gist.", ("Point",)),
)


class FakeRunner:
    def __init__(self, outcome: PipelineResult | BaseException = RESULT) -> None:
        self._outcome = outcome
        self.calls: list[tuple[VideoId, str]] = []

    def run(
        self, video_id: VideoId, language: str, on_progress: ProgressCallback
    ) -> PipelineResult:
        self.calls.append((video_id, language))
        on_progress(Progress(PipelineStage.CHECKING_VIDEO))
        on_progress(Progress(PipelineStage.TRANSCRIBING, step=1, total=2))
        on_progress(Progress(PipelineStage.SUMMARIZING, step=2, total=5))
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        on_progress(Progress(PipelineStage.DONE))
        return self._outcome


class LoggingSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[LogLevel, list[str]]] = []

    def __call__(
        self, level: LogLevel, *, secrets: Iterable[str] = (), stream: TextIO | None = None
    ) -> None:
        self.calls.append((level, list(secrets)))


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    # A developer's real .env or exported variables must never leak into test results.
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name == "GROQ_API_KEY" or name.startswith("VIDBRIEF_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GROQ_API_KEY", FAKE_API_KEY)
    return Settings()


class Run:
    def __init__(self, settings: Settings, runner: FakeRunner | None = None) -> None:
        self.runner = runner or FakeRunner()
        self.logging = LoggingSpy()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.built = 0
        self._settings = settings

    def __call__(self, *argv: str) -> int:
        def build(settings: Settings) -> FakeRunner:
            self.built += 1
            return self.runner

        return main(
            list(argv),
            load_settings=lambda: self._settings,
            build=build,
            setup_logging=self.logging,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def test_prints_the_markdown_summary(settings: Settings) -> None:
    run = Run(settings)

    assert run(URL) == 0

    assert run.stdout.getvalue() == to_markdown(RESULT)
    assert run.runner.calls == [(VIDEO_ID, "pt-BR")]


def test_shows_progress_on_stderr(settings: Settings) -> None:
    run = Run(settings)

    run(URL)

    assert run.stderr.getvalue().splitlines() == [
        "Checking the video...",
        "Transcribing the audio (1/2)...",
        "Summarizing (2/~5)...",
    ]


def test_uses_the_requested_language(settings: Settings) -> None:
    run = Run(settings)

    run(URL, "--language", "en")

    assert run.runner.calls == [(VIDEO_ID, "en")]


def test_rejects_languages_outside_the_allowlist(settings: Settings) -> None:
    with pytest.raises(SystemExit) as caught:
        Run(settings)(URL, "--language", "klingon")

    assert caught.value.code == 2


def test_invalid_links_fail_before_building_the_pipeline(settings: Settings) -> None:
    run = Run(settings)

    assert run("https://evil.example/watch?v=jNQXAC9IVRw") == 1

    assert run.stderr.getvalue() == "Error: Please enter a valid YouTube video link.\n"
    assert run.built == 0


def test_pipeline_errors_show_the_safe_message(settings: Settings) -> None:
    run = Run(settings, FakeRunner(VideoTooLongError(7200)))

    assert run(URL) == 1

    assert run.stderr.getvalue().endswith(
        "Error: Videos longer than 120 minutes are not supported.\n"
    )
    assert run.stdout.getvalue() == ""


def test_missing_programs_are_reported_before_any_work(settings: Settings) -> None:
    run = Run(settings)

    def build(settings: Settings) -> FakeRunner:
        raise MissingDependencyError("deno")

    code = main(
        [URL],
        load_settings=lambda: settings,
        build=build,
        setup_logging=run.logging,
        stdout=run.stdout,
        stderr=run.stderr,
    )

    assert code == 1
    assert "'deno'" in run.stderr.getvalue()
    assert run.runner.calls == []


def test_ctrl_c_exits_quietly(settings: Settings) -> None:
    run = Run(settings, FakeRunner(KeyboardInterrupt()))

    assert run(URL) == 130

    assert run.stderr.getvalue().endswith("Cancelled.\n")


def test_quiet_logging_by_default_and_the_key_is_always_masked(settings: Settings) -> None:
    run = Run(settings)

    run(URL)

    assert run.logging.calls == [("ERROR", [FAKE_API_KEY])]


def test_verbose_uses_the_configured_log_level(settings: Settings) -> None:
    run = Run(settings)

    run(URL, "--verbose")

    assert run.logging.calls == [("INFO", [FAKE_API_KEY])]


def test_configuration_errors_name_the_fields_without_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name == "GROQ_API_KEY" or name.startswith("VIDBRIEF_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("VIDBRIEF_PORT", "not-a-port")
    stderr = io.StringIO()

    code = main([URL], stdout=io.StringIO(), stderr=stderr, setup_logging=LoggingSpy())

    assert code == 2
    message = stderr.getvalue()
    assert "GROQ_API_KEY" in message
    assert "port" in message
    assert "not-a-port" not in message


def test_module_entry_point_exits_with_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "main", lambda: 7)

    with pytest.raises(SystemExit) as caught:
        runpy.run_module("vidbrief", run_name="__main__")

    assert caught.value.code == 7
