"""Domain errors that carry a message safe to show to end users."""

from typing import ClassVar


class VidbriefError(Exception):
    """Base class for expected failures in the summarization pipeline.

    Attributes:
        reason: A fixed, machine-readable code (e.g. ``"host_not_allowed"``) meant for logs.
            It never includes raw user input or text from external services.
    """

    _user_message: ClassVar[str] = "Something went wrong. Please try again."

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    @property
    def user_message(self) -> str:
        """A generic text that is safe to show in the UI."""
        return self._user_message


class InvalidVideoUrlError(VidbriefError):
    """Raised when user input is not an accepted YouTube video URL."""

    _user_message = "Please enter a valid YouTube video link."


class VideoUnavailableError(VidbriefError):
    """Raised for private, removed, region-blocked, age-restricted or members-only videos."""

    _user_message = "This video is unavailable or restricted and cannot be summarized."


class LiveStreamNotSupportedError(VidbriefError):
    """Raised for streams that are live, scheduled or still being processed."""

    _user_message = "Live and upcoming streams can only be summarized after they have ended."


class VideoDurationUnknownError(VidbriefError):
    """Raised when the video length cannot be determined, so limits cannot be enforced."""

    _user_message = "The length of this video could not be determined, so it cannot be summarized."


class VideoTooLongError(VidbriefError):
    """Raised when a video exceeds the configured maximum duration.

    Attributes:
        max_duration_seconds: The configured limit that was exceeded.
    """

    def __init__(self, max_duration_seconds: int) -> None:
        super().__init__("too_long")
        self.max_duration_seconds = max_duration_seconds

    @property
    def user_message(self) -> str:
        """A generic text that is safe to show in the UI."""
        return f"Videos longer than {_describe_limit(self.max_duration_seconds)} are not supported."


class CaptionsUnavailableError(VidbriefError):
    """Raised when a caption track cannot be turned into a transcript."""

    _user_message = "Captions for this video could not be retrieved."


class AudioProcessingError(VidbriefError):
    """Raised when the audio cannot be downloaded, converted or split for transcription."""

    _user_message = "We couldn't process this video's audio."


class ExternalServiceError(VidbriefError):
    """Raised when a third-party service fails or returns something unexpected."""

    _user_message = "A required service is temporarily unavailable. Please try again later."


def _describe_limit(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60} minutes"
    return f"{seconds} seconds"
