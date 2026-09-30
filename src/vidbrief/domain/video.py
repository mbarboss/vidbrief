"""YouTube video identity and strict parsing of user-supplied video URLs."""

import re
from dataclasses import dataclass
from urllib.parse import SplitResult, parse_qs, urlsplit

from vidbrief.domain.errors import InvalidVideoUrlError

_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
# Anything outside visible ASCII, plus backslash, is rejected up front: browsers and Python's
# URL parser disagree on how to treat them, which is the basis of host-confusion attacks
# such as ``https://www.youtube.com\@evil.com``.
_FORBIDDEN_CHARS_RE = re.compile(r"[^\x21-\x7e]|\\")
_MAX_URL_LENGTH = 2048
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_SHORT_LINK_HOST = "youtu.be"
_YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "www.youtube-nocookie.com"}
)
_ID_PATH_PREFIXES = frozenset({"shorts", "live", "embed"})


@dataclass(frozen=True, slots=True)
class VideoId:
    """A validated 11-character YouTube video identifier.

    Raises:
        ValueError: If ``value`` is not exactly 11 URL-safe base64 characters.
    """

    value: str

    def __post_init__(self) -> None:
        if not _VIDEO_ID_RE.fullmatch(self.value):
            raise ValueError("invalid video id")

    @property
    def canonical_url(self) -> str:
        """The only URL form handed to downstream tools, rebuilt from the validated ID."""
        return f"https://www.youtube.com/watch?v={self.value}"


def parse_youtube_url(raw: str) -> VideoId:
    """Extract the video ID from a user-supplied YouTube URL.

    Accepts ``watch?v=``, ``youtu.be/``, ``shorts/``, ``live/`` and ``embed/`` links on
    allowlisted hosts, with or without an ``http(s)://`` prefix. Extra query parameters and
    fragments are ignored.

    Raises:
        InvalidVideoUrlError: If the input is not an accepted YouTube video URL. Its
            ``reason`` code explains why without echoing the input.
    """
    candidate = raw.strip()
    if not candidate:
        raise InvalidVideoUrlError("empty")
    if len(candidate) > _MAX_URL_LENGTH:
        raise InvalidVideoUrlError("too_long")
    if _FORBIDDEN_CHARS_RE.search(candidate):
        raise InvalidVideoUrlError("invalid_characters")
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parts = _split_url(candidate)
    _require_allowed_origin(parts)

    try:
        return VideoId(_extract_video_id(parts) or "")
    except ValueError:
        raise InvalidVideoUrlError("invalid_video_id") from None


def _split_url(candidate: str) -> SplitResult:
    try:
        return urlsplit(candidate)
    except ValueError:
        raise InvalidVideoUrlError("malformed_url") from None


def _require_allowed_origin(parts: SplitResult) -> None:
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise InvalidVideoUrlError("scheme_not_allowed")
    if "@" in parts.netloc:
        raise InvalidVideoUrlError("userinfo_not_allowed")
    try:
        port = parts.port
    except ValueError:
        raise InvalidVideoUrlError("port_not_allowed") from None
    if port is not None:
        raise InvalidVideoUrlError("port_not_allowed")
    host = parts.hostname or ""
    if host != _SHORT_LINK_HOST and host not in _YOUTUBE_HOSTS:
        raise InvalidVideoUrlError("host_not_allowed")


def _extract_video_id(parts: SplitResult) -> str | None:
    segments = parts.path.strip("/").split("/")
    if parts.hostname == _SHORT_LINK_HOST:
        return segments[0] if len(segments) == 1 else None
    if segments == ["watch"]:
        # A repeated ``v`` is ambiguous (parsers disagree on first vs last), so it is rejected
        # instead of guessing which video the user meant.
        values = parse_qs(parts.query).get("v", [])
        return values[0] if len(values) == 1 else None
    if len(segments) == 2 and segments[0] in _ID_PATH_PREFIXES:
        return segments[1]
    return None
