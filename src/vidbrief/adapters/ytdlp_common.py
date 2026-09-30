"""Building blocks shared by every adapter that drives yt-dlp."""

import logging
from collections.abc import Callable
from typing import Any, Protocol, Self

_ytdlp_logger = logging.getLogger("vidbrief.adapters.ytdlp")


class InfoExtractor(Protocol):
    """The subset of ``yt_dlp.YoutubeDL`` the adapters rely on."""

    def __enter__(self) -> Self: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def extract_info(self, url: str, download: bool) -> Any: ...


YoutubeDLFactory = Callable[[dict[str, Any]], InfoExtractor]


class YtDlpLogger:
    """Forwards yt-dlp output into standard logging instead of stdout/stderr."""

    def debug(self, message: str) -> None:
        _ytdlp_logger.debug(message)

    def info(self, message: str) -> None:
        # yt-dlp's "info" is progress chatter, not an application-level event.
        _ytdlp_logger.debug(message)

    def warning(self, message: str) -> None:
        _ytdlp_logger.warning(message)

    def error(self, message: str) -> None:
        _ytdlp_logger.error(message)


def base_options(socket_timeout_seconds: float) -> dict[str, Any]:
    """Return a fresh set of yt-dlp options every adapter starts from.

    Media downloads are off unless an adapter explicitly opts in.
    """
    # No cookie options on purpose: restricted videos are rejected rather than accessed
    # with the user's Google session.
    return {
        "skip_download": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "socket_timeout": socket_timeout_seconds,
        "logger": YtDlpLogger(),
    }
