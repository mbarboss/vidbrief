"""Tests for wiring the real adapters into the pipeline."""

import os
from pathlib import Path

import pytest

from vidbrief.composition import build_pipeline
from vidbrief.config import Settings
from vidbrief.domain.errors import MissingDependencyError
from vidbrief.services.pipeline import SummaryPipeline

FAKE_API_KEY = "gsk_test_not_a_real_key"  # pragma: allowlist secret


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    # A developer's real .env or exported variables must never leak into test results.
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name == "GROQ_API_KEY" or name.startswith("VIDBRIEF_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GROQ_API_KEY", FAKE_API_KEY)
    return Settings()


def _installed(monkeypatch: pytest.MonkeyPatch, *missing: str) -> None:
    monkeypatch.setattr(
        "vidbrief.adapters.programs.shutil.which",
        lambda name: None if name in missing else f"/opt/bin/{name}",
    )


def test_builds_the_pipeline_without_touching_the_network(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    _installed(monkeypatch)

    assert isinstance(build_pipeline(settings), SummaryPipeline)


@pytest.mark.parametrize("missing", ["deno", "ffmpeg", "ffprobe"])
def test_refuses_to_start_without_a_required_program(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, missing: str
) -> None:
    _installed(monkeypatch, missing)

    with pytest.raises(MissingDependencyError) as caught:
        build_pipeline(settings)

    assert caught.value.tool == missing
