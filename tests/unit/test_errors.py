"""Tests for domain errors and their user-facing messages."""

import pytest

from vidbrief.domain.errors import (
    ExternalServiceError,
    InvalidVideoUrlError,
    LiveStreamNotSupportedError,
    MissingDependencyError,
    NoSpeechDetectedError,
    RateLimitedError,
    TooManyJobsError,
    UnsupportedLanguageError,
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
        RateLimitedError("summary_rate_limited"),
        NoSpeechDetectedError("no_speech"),
        UnsupportedLanguageError("unsupported_language"),
        MissingDependencyError("deno"),
        TooManyJobsError(),
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


def test_rate_limit_is_an_external_service_failure_with_its_own_message() -> None:
    error = RateLimitedError("summary_rate_limited")

    assert isinstance(error, ExternalServiceError)
    assert error.user_message != ExternalServiceError("network").user_message
    assert "try again later" in error.user_message


def test_missing_dependency_names_the_program_and_points_to_the_readme() -> None:
    error = MissingDependencyError("deno")

    assert error.reason == "deno_not_found"
    assert error.tool == "deno"
    assert "'deno'" in error.user_message
    assert "README" in error.user_message
