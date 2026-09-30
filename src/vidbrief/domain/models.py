"""Value objects shared across the summarization pipeline."""

from dataclasses import dataclass
from enum import StrEnum

from vidbrief.domain.video import VideoId


class LiveStatus(StrEnum):
    """Broadcast state of a video, mirroring the values reported by YouTube."""

    NOT_LIVE = "not_live"
    IS_LIVE = "is_live"
    IS_UPCOMING = "is_upcoming"
    WAS_LIVE = "was_live"
    POST_LIVE = "post_live"


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """What is known about a video before any transcript is fetched.

    ``title`` comes from the uploader and must be treated as untrusted text wherever it is
    rendered or embedded. ``duration_seconds`` is ``None`` when YouTube does not report it.
    Caption fields hold language codes of manual and auto-generated captions respectively.
    """

    video_id: VideoId
    title: str
    duration_seconds: int | None
    thumbnail_url: str | None
    live_status: LiveStatus
    caption_languages: tuple[str, ...] = ()
    auto_caption_languages: tuple[str, ...] = ()
