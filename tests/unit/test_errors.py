"""Tests for domain errors and the text they show to users."""

import re

import pytest

from vidbrief.domain.errors import (
    AudioProcessingError,
    CaptionsUnavailableError,
    ExternalServiceError,
    InvalidVideoUrlError,
    LiveStreamNotSupportedError,
    MissingDependencyError,
    NoSpeechDetectedError,
    RateLimitedError,
    TooManyJobsError,
    UnexpectedError,
    UnsupportedLanguageError,
    VidbriefError,
    VideoDurationUnknownError,
    VideoTooLongError,
    VideoUnavailableError,
)

GROQ_SERVICES = ("transcription", "summary")
REASON_CODE_RE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
ERRORS = [
    InvalidVideoUrlError("host_not_allowed"),
    *(
        VideoUnavailableError(reason)
        for reason in (
            "private",
            "removed",
            "members_only",
            "geo_blocked",
            "age_restricted",
            "unavailable",
        )
    ),
    *(LiveStreamNotSupportedError(reason) for reason in ("is_live", "is_upcoming", "post_live")),
    VideoDurationUnknownError("missing_duration"),
    VideoTooLongError(7200),
    CaptionsUnavailableError("empty"),
    AudioProcessingError("command_failed"),
    *(
        ExternalServiceError(reason)
        for reason in ("bot_check", "download_failed", "unexpected_response", "network")
    ),
    *(
        ExternalServiceError(f"{service}_{suffix}")
        for service in GROQ_SERVICES
        for suffix in ("auth_failed", "unavailable", "rejected", "bad_response")
    ),
    ExternalServiceError("summary_too_long"),
    RateLimitedError("summary_rate_limited"),
    NoSpeechDetectedError("no_speech"),
    UnsupportedLanguageError("unsupported_language"),
    MissingDependencyError("deno"),
    TooManyJobsError(),
    UnexpectedError(),
]


@pytest.mark.parametrize("error", ERRORS, ids=lambda error: error.reason)
def test_errors_share_a_safe_contract(error: VidbriefError) -> None:
    assert isinstance(error, VidbriefError)
    assert error.reason
    assert str(error) == error.reason
    for text in (error.user_message, error.user_hint or ""):
        assert not REASON_CODE_RE.search(text)
        assert "—" not in text
    assert error.user_message.endswith(".")
    assert error.user_hint is None or error.user_hint.endswith(".")


@pytest.mark.parametrize(
    ("error", "message", "hint"),
    [
        (VideoUnavailableError("private"), "This video is private.", None),
        (VideoUnavailableError("removed"), "This video has been removed.", None),
        (
            VideoUnavailableError("members_only"),
            "This video is for channel members only.",
            None,
        ),
        (
            VideoUnavailableError("geo_blocked"),
            "This video isn't available in your country.",
            None,
        ),
        (
            VideoUnavailableError("age_restricted"),
            "This video is age-restricted.",
            "vidbrief never signs in to YouTube, so it can't open it.",
        ),
        (
            VideoUnavailableError("unavailable"),
            "YouTube says this video isn't available.",
            "Check that the link opens in a private browser window.",
        ),
        (
            LiveStreamNotSupportedError("is_live"),
            "This stream is still live.",
            "Try again once it has ended.",
        ),
        (
            LiveStreamNotSupportedError("is_upcoming"),
            "This stream hasn't started yet.",
            "Try again once it has ended.",
        ),
        (
            LiveStreamNotSupportedError("post_live"),
            "This stream just ended and YouTube is still processing it.",
            "Try again in a little while.",
        ),
        (
            VideoDurationUnknownError("missing_duration"),
            "YouTube didn't say how long this video is, so it can't be checked against the limit.",
            None,
        ),
        (
            ExternalServiceError("bot_check"),
            "YouTube wants this computer to prove it isn't a bot.",
            "Wait a while and try again.",
        ),
        (
            ExternalServiceError("download_failed"),
            "YouTube didn't send this video.",
            "Try again in a few minutes.",
        ),
        (
            ExternalServiceError("unexpected_response"),
            "YouTube didn't send this video.",
            "Try again in a few minutes.",
        ),
        (
            ExternalServiceError("summary_too_long"),
            "This video is too long to summarize within your Groq limits.",
            None,
        ),
        (
            RateLimitedError("transcription_rate_limited"),
            "You've hit Groq's usage limit for now.",
            "Try again in a few minutes, or tomorrow if you've summarized a lot today.",
        ),
        (
            AudioProcessingError("split_failed"),
            "Something went wrong while preparing the audio.",
            "Try again. The server log says what failed.",
        ),
        (
            NoSpeechDetectedError("no_speech"),
            "Nobody seems to speak in this video, so there's nothing to summarize.",
            None,
        ),
        (
            UnexpectedError(),
            "Something unexpected went wrong.",
            "Try again. The server log has the details.",
        ),
        (
            ExternalServiceError("network"),
            "A service vidbrief relies on didn't answer as expected.",
            "Try again in a few minutes.",
        ),
    ],
    ids=lambda value: value.reason if isinstance(value, VidbriefError) else "",
)
def test_each_reason_explains_itself(error: VidbriefError, message: str, hint: str | None) -> None:
    assert error.user_message == message
    assert error.user_hint == hint


@pytest.mark.parametrize("service", GROQ_SERVICES)
@pytest.mark.parametrize(
    ("suffix", "message", "hint"),
    [
        (
            "auth_failed",
            "Groq didn't accept the API key.",
            "Check GROQ_API_KEY in .env, then restart vidbrief.",
        ),
        ("unavailable", "Groq isn't responding right now.", "Try again in a few minutes."),
        (
            "rejected",
            "Groq sent back an answer vidbrief couldn't use.",
            "Trying again usually works.",
        ),
        (
            "bad_response",
            "Groq sent back an answer vidbrief couldn't use.",
            "Trying again usually works.",
        ),
        ("request_too_large", "This video is too long to summarize within your Groq limits.", None),
    ],
)
def test_groq_failures_read_the_same_for_both_services(
    service: str, suffix: str, message: str, hint: str | None
) -> None:
    error = ExternalServiceError(f"{service}_{suffix}")

    assert error.user_message == message
    assert error.user_hint == hint


def test_a_truncated_summary_reads_like_an_unusable_answer() -> None:
    error = ExternalServiceError("summary_truncated")

    assert error.user_message == "Groq sent back an answer vidbrief couldn't use."
    assert error.retryable


@pytest.mark.parametrize(
    "error",
    [
        LiveStreamNotSupportedError("is_live"),
        AudioProcessingError("command_timeout"),
        ExternalServiceError("bot_check"),
        ExternalServiceError("summary_unavailable"),
        ExternalServiceError("transcription_auth_failed"),
        RateLimitedError("summary_rate_limited"),
        UnexpectedError(),
    ],
    ids=lambda error: error.reason,
)
def test_temporary_failures_are_worth_retrying(error: VidbriefError) -> None:
    assert error.retryable


@pytest.mark.parametrize(
    "error",
    [
        InvalidVideoUrlError("host_not_allowed"),
        VideoUnavailableError("private"),
        VideoDurationUnknownError("missing_duration"),
        VideoTooLongError(7200),
        ExternalServiceError("summary_too_long"),
        ExternalServiceError("transcription_request_too_large"),
        NoSpeechDetectedError("no_speech"),
        TooManyJobsError(),
    ],
    ids=lambda error: error.reason,
)
def test_permanent_failures_are_not(error: VidbriefError) -> None:
    assert not error.retryable


class TestVideoTooLongError:
    def test_names_the_limit_and_how_to_raise_it(self) -> None:
        error = VideoTooLongError(7200)

        assert error.reason == "too_long"
        assert error.max_duration_seconds == 7200
        assert error.user_message == (
            "This video is longer than 2 hours, the most vidbrief summarizes."
        )
        assert error.user_hint == "You can raise VIDBRIEF_MAX_VIDEO_DURATION_SECONDS in .env."

    def test_names_uneven_limits_exactly(self) -> None:
        assert "longer than 90 seconds," in VideoTooLongError(90).user_message


def test_rate_limit_is_an_external_service_failure() -> None:
    assert isinstance(RateLimitedError("summary_rate_limited"), ExternalServiceError)


def test_missing_dependency_names_the_program_and_points_to_the_readme() -> None:
    error = MissingDependencyError("deno")

    assert error.reason == "deno_not_found"
    assert error.tool == "deno"
    assert "'deno'" in error.user_message
    assert "README" in error.user_message
    assert error.user_hint is None


def test_unexpected_errors_have_a_fixed_reason() -> None:
    assert UnexpectedError().reason == "unexpected"
