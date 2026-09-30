"""Tests for locating external programs."""

import pytest

from vidbrief.adapters.programs import find_program
from vidbrief.domain.errors import MissingDependencyError


def test_returns_the_resolved_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vidbrief.adapters.programs.shutil.which", lambda name: f"/opt/{name}")

    assert find_program("deno") == "/opt/deno"


def test_raises_a_missing_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vidbrief.adapters.programs.shutil.which", lambda name: None)

    with pytest.raises(MissingDependencyError) as caught:
        find_program("deno")

    assert caught.value.reason == "deno_not_found"
