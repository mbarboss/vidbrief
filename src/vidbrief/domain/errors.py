"""Domain errors that carry a message safe to show to end users."""

from typing import ClassVar


class VidbriefError(Exception):
    """Base class for expected failures in the summarization pipeline.

    ``user_message`` is a fixed, generic text for the UI; details for operators live in the
    exception arguments and must never contain raw user input.
    """

    user_message: ClassVar[str] = "Something went wrong. Please try again."


class InvalidVideoUrlError(VidbriefError):
    """Raised when user input is not an accepted YouTube video URL.

    Attributes:
        reason: A fixed, machine-readable code (e.g. ``"host_not_allowed"``) that is safe
            to log because it never includes the rejected input.
    """

    user_message: ClassVar[str] = "Please enter a valid YouTube video link."

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
