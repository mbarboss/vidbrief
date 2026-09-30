"""Tests for domain errors and their user-facing messages."""

import pytest

from vidbrief.domain.errors import (
    ExternalServiceError,
    InvalidVideoUrlError,
    LiveStreamNotSupportedError,
    VidbriefError,
    VideoDurationUnknownError,
    VideoTooLongError,
    VideoUnavailableError,
)


@pytest.mark.parametrize(
    "error",
    [
        InvalidVideoUrlError("host_not_allowed"),
        VideoUnavailableError("private"),
        LiveStreamNotSupportedError("is_live"),
        VideoDurationUnknownError("missing_duration"),
        ExternalServiceError("network"),
        VideoTooLongError(7200),
    ],
    ids=type,
)
def test_errors_share_a_safe_contract(error: VidbriefError) -> None:
    assert isinstance(error, VidbriefError)
    assert error.reason
    assert str(error) == error.reason
    assert error.user_message
    assert error.reason not in error.user_message


class TestVideoTooLongError:
    def test_reports_the_limit_in_minutes(self) -> None:
        error = VideoTooLongError(7200)

        assert error.reason == "too_long"
        assert error.max_duration_seconds == 7200
        assert error.user_message == "Videos longer than 120 minutes are not supported."

    def test_falls_back_to_seconds_for_uneven_limits(self) -> None:
        error = VideoTooLongError(90)

        assert error.user_message == "Videos longer than 90 seconds are not supported."
