"""Domain errors that carry text safe to show to end users."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from vidbrief.domain.durations import describe_duration

_GROQ_SERVICES = ("transcription", "summary")


@dataclass(frozen=True, slots=True)
class ErrorText:
    """What users are told about a failure.

    Attributes:
        message: What went wrong, in one sentence.
        hint: What the user can do about it, if anything.
        retryable: Whether the same request may succeed later.
    """

    message: str
    hint: str | None = None
    retryable: bool = False


def _for_groq(texts: Mapping[str, ErrorText]) -> dict[str, ErrorText]:
    return {
        f"{service}_{suffix}": text for service in _GROQ_SERVICES for suffix, text in texts.items()
    }


class VidbriefError(Exception):
    """Base class for expected failures in the summarization pipeline.

    Subclasses describe themselves with ``_text`` and may refine it per reason with
    ``_text_by_reason``; both are fixed strings, so nothing external is ever shown.

    Attributes:
        reason: A fixed, machine-readable code (e.g. ``"host_not_allowed"``) meant for logs.
            It never includes raw user input or text from external services.
    """

    _text: ClassVar[ErrorText] = ErrorText("Something unexpected went wrong.")
    _text_by_reason: ClassVar[Mapping[str, ErrorText]] = MappingProxyType({})

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    @property
    def user_message(self) -> str:
        """A text that is safe to show in the UI."""
        return self._resolved_text.message

    @property
    def user_hint(self) -> str | None:
        """What the user can do about the failure, if anything; safe to show in the UI."""
        return self._resolved_text.hint

    @property
    def retryable(self) -> bool:
        """Whether sending the same request again later may succeed."""
        return self._resolved_text.retryable

    @property
    def _resolved_text(self) -> ErrorText:
        return self._text_by_reason.get(self.reason, self._text)


class InvalidVideoUrlError(VidbriefError):
    """Raised when user input is not an accepted YouTube video URL."""

    _text = ErrorText("Please enter a valid YouTube video link.")


class VideoUnavailableError(VidbriefError):
    """Raised for private, removed, region-blocked, age-restricted or members-only videos."""

    _text = ErrorText(
        "YouTube says this video isn't available.",
        "Check that the link opens in a private browser window.",
    )
    _text_by_reason = MappingProxyType(
        {
            "private": ErrorText("This video is private."),
            "removed": ErrorText("This video has been removed."),
            "members_only": ErrorText("This video is for channel members only."),
            "geo_blocked": ErrorText("This video isn't available in your country."),
            "age_restricted": ErrorText(
                "This video is age-restricted.",
                "vidbrief never signs in to YouTube, so it can't open it.",
            ),
        }
    )


class LiveStreamNotSupportedError(VidbriefError):
    """Raised for streams that are live, scheduled or still being processed."""

    _text = ErrorText(
        "Live streams can only be summarized after they have ended.",
        "Try again once it has ended.",
        retryable=True,
    )
    _text_by_reason = MappingProxyType(
        {
            "is_live": ErrorText(
                "This stream is still live.", "Try again once it has ended.", retryable=True
            ),
            "is_upcoming": ErrorText(
                "This stream hasn't started yet.", "Try again once it has ended.", retryable=True
            ),
            "post_live": ErrorText(
                "This stream just ended and YouTube is still processing it.",
                "Try again in a little while.",
                retryable=True,
            ),
        }
    )


class VideoDurationUnknownError(VidbriefError):
    """Raised when the video length cannot be determined, so limits cannot be enforced."""

    _text = ErrorText(
        "YouTube didn't say how long this video is, so it can't be checked against the limit."
    )


class VideoTooLongError(VidbriefError):
    """Raised when a video exceeds the configured maximum duration.

    Attributes:
        max_duration_seconds: The configured limit that was exceeded.
    """

    _text = ErrorText(
        "This video is too long.", "You can raise VIDBRIEF_MAX_VIDEO_DURATION_SECONDS in .env."
    )

    def __init__(self, max_duration_seconds: int) -> None:
        super().__init__("too_long")
        self.max_duration_seconds = max_duration_seconds

    @property
    def user_message(self) -> str:
        """A text that is safe to show in the UI and names the limit."""
        limit = describe_duration(self.max_duration_seconds)
        return f"This video is longer than {limit}, the most vidbrief summarizes."


class CaptionsUnavailableError(VidbriefError):
    """Raised when a caption track cannot be turned into a transcript."""

    _text = ErrorText("Captions for this video could not be retrieved.")


class AudioProcessingError(VidbriefError):
    """Raised when the audio cannot be downloaded, converted or split for transcription."""

    _text = ErrorText(
        "Something went wrong while preparing the audio.",
        "Try again. The server log says what failed.",
        retryable=True,
    )


_YOUTUBE_DID_NOT_SEND = ErrorText(
    "YouTube didn't send this video.", "Try again in a few minutes.", retryable=True
)
_GROQ_UNUSABLE_ANSWER = ErrorText(
    "Groq sent back an answer vidbrief couldn't use.",
    "Trying again usually works.",
    retryable=True,
)
_TOO_LONG_FOR_GROQ = ErrorText("This video is too long to summarize within your Groq limits.")


class ExternalServiceError(VidbriefError):
    """Raised when a third-party service fails or returns something unexpected."""

    _text = ErrorText(
        "A service vidbrief relies on didn't answer as expected.",
        "Try again in a few minutes.",
        retryable=True,
    )
    _text_by_reason = MappingProxyType(
        {
            "bot_check": ErrorText(
                "YouTube wants this computer to prove it isn't a bot.",
                "Wait a while and try again.",
                retryable=True,
            ),
            "download_failed": _YOUTUBE_DID_NOT_SEND,
            "unexpected_response": _YOUTUBE_DID_NOT_SEND,
            "summary_too_long": _TOO_LONG_FOR_GROQ,
            "summary_truncated": _GROQ_UNUSABLE_ANSWER,
            **_for_groq(
                {
                    "auth_failed": ErrorText(
                        "Groq didn't accept the API key.",
                        "Check GROQ_API_KEY in .env, then restart vidbrief.",
                        retryable=True,
                    ),
                    "unavailable": ErrorText(
                        "Groq isn't responding right now.",
                        "Try again in a few minutes.",
                        retryable=True,
                    ),
                    "rejected": _GROQ_UNUSABLE_ANSWER,
                    "bad_response": _GROQ_UNUSABLE_ANSWER,
                    "request_too_large": _TOO_LONG_FOR_GROQ,
                }
            ),
        }
    )


class RateLimitedError(ExternalServiceError):
    """Raised when an AI service quota is exhausted for longer than it is worth waiting."""

    _text = ErrorText(
        "You've hit Groq's usage limit for now.",
        "Try again in a few minutes, or tomorrow if you've summarized a lot today.",
        retryable=True,
    )
    _text_by_reason = MappingProxyType({})


class NoSpeechDetectedError(VidbriefError):
    """Raised when speech-to-text finds nothing said in the audio."""

    _text = ErrorText("Nobody seems to speak in this video, so there's nothing to summarize.")


class MissingDependencyError(VidbriefError):
    """Raised at startup when a program vidbrief needs is not installed.

    Attributes:
        tool: The program name, always chosen by vidbrief and never taken from user input.
    """

    def __init__(self, tool: str) -> None:
        super().__init__(f"{tool}_not_found")
        self.tool = tool

    @property
    def user_message(self) -> str:
        """A text that is safe to show in the UI and names the missing program."""
        return (
            f"The required program '{self.tool}' was not found. Install it and make sure it "
            "is on your PATH (see the README)."
        )


class UnsupportedLanguageError(VidbriefError):
    """Raised when a summary is requested in a language outside the allowlist."""

    _text = ErrorText("Please choose one of the supported summary languages.")


class TooManyJobsError(VidbriefError):
    """Raised when a summary is requested while the concurrent job limit is reached."""

    _text = ErrorText("Another summary is still running. Try again when it finishes.")

    def __init__(self) -> None:
        super().__init__("too_many_jobs")


class UnexpectedError(VidbriefError):
    """Stands in for a bug or an unforeseen failure, whose details stay in the logs."""

    _text = ErrorText(
        "Something unexpected went wrong.",
        "Try again. The server log has the details.",
        retryable=True,
    )

    def __init__(self) -> None:
        super().__init__("unexpected")
