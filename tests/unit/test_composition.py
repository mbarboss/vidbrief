"""Tests for wiring the real adapters into the pipeline."""

import os
import shutil
from pathlib import Path

import pytest

from vidbrief.composition import build_pipeline
from vidbrief.config import Settings
from vidbrief.services.pipeline import SummaryPipeline

FAKE_API_KEY = "gsk_test_not_a_real_key"  # pragma: allowlist secret


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_builds_the_pipeline_without_touching_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A developer's real .env or exported variables must never leak into test results.
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name == "GROQ_API_KEY" or name.startswith("VIDBRIEF_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GROQ_API_KEY", FAKE_API_KEY)

    assert isinstance(build_pipeline(Settings()), SummaryPipeline)
