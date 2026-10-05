"""Tests that keep CHANGELOG.md in step with the package version."""

import re
from datetime import date
from importlib.metadata import version
from pathlib import Path

import pytest

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?$", re.M)


@pytest.fixture(scope="module")
def changelog() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def headings(changelog: str) -> list[re.Match[str]]:
    return list(HEADING.finditer(changelog))


def test_starts_with_an_unreleased_section(headings: list[re.Match[str]]) -> None:
    assert headings[0]["name"] == "Unreleased"
    assert headings[0]["date"] is None


def test_latest_release_matches_the_package_version(headings: list[re.Match[str]]) -> None:
    assert headings[1]["name"] == version("vidbrief")


def test_every_release_has_a_valid_date(headings: list[re.Match[str]]) -> None:
    for heading in headings[1:]:
        assert heading["date"] is not None, heading[0]
        date.fromisoformat(heading["date"])


def test_every_section_has_a_link_reference(changelog: str, headings: list[re.Match[str]]) -> None:
    for heading in headings:
        reference = f"[{heading['name']}]: https://github.com/mbarboss/vidbrief/"
        assert reference in changelog, heading[0]
