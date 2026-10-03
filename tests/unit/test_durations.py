"""Tests for durations written the way people say them."""

import pytest

from vidbrief.domain.durations import describe_duration


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (7200, "2 hours"),
        (3600, "1 hour"),
        (5400, "90 minutes"),
        (60, "1 minute"),
        (90, "90 seconds"),
        (45, "45 seconds"),
        (1, "1 second"),
    ],
)
def test_describe_duration(seconds: int, expected: str) -> None:
    assert describe_duration(seconds) == expected
