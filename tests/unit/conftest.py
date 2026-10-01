"""Fixtures shared by the unit tests."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from vidbrief.config import Settings

FAKE_API_KEY = "gsk_test_not_a_real_key"  # pragma: allowlist secret

SettingsFactory = Callable[..., Settings]


@pytest.fixture
def make_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SettingsFactory:
    """Build settings from the given ``VIDBRIEF_*`` overrides only.

    A developer's real ``.env`` or exported variables must never leak into test results.
    """
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name == "GROQ_API_KEY" or name.startswith("VIDBRIEF_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GROQ_API_KEY", FAKE_API_KEY)

    def make(**overrides: str) -> Settings:
        for name, value in overrides.items():
            monkeypatch.setenv(f"VIDBRIEF_{name.upper()}", value)
        return Settings()

    return make
