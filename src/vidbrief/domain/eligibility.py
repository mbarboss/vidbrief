"""Rules that decide whether a video can go through the summarization pipeline."""

from vidbrief.domain.errors import (
    LiveStreamNotSupportedError,
    VideoDurationUnknownError,
    VideoTooLongError,
)
from vidbrief.domain.models import LiveStatus, VideoMetadata

# Unfinished streams have neither complete audio nor final captions, so any summary would
# silently cover only part of the content.
_UNFINISHED_STREAMS = frozenset({LiveStatus.IS_LIVE, LiveStatus.IS_UPCOMING, LiveStatus.POST_LIVE})
# Very fast speech is about 18 characters per second; more than twice that means the text
# is not a transcript of this video.
_MAX_CHARS_PER_SECOND = 40
_MIN_ALLOWANCE_SECONDS = 60


def ensure_summarizable(metadata: VideoMetadata, max_duration_seconds: int) -> None:
    """Reject videos the pipeline cannot or should not process.

    Raises:
        LiveStreamNotSupportedError: If the stream has not finished.
        VideoDurationUnknownError: If the duration is unknown, since the cost limit could
            not be enforced.
        VideoTooLongError: If the video exceeds ``max_duration_seconds``.
    """
    if metadata.live_status in _UNFINISHED_STREAMS:
        raise LiveStreamNotSupportedError(metadata.live_status.value)
    if metadata.duration_seconds is None:
        raise VideoDurationUnknownError("missing_duration")
    if metadata.duration_seconds > max_duration_seconds:
        raise VideoTooLongError(max_duration_seconds)


def is_plausible_transcript(text: str, duration_seconds: int) -> bool:
    """Tell whether ``text`` is short enough to be what is said in the video.

    Manual captions are uploaded by the video's owner, so a short video could carry
    megabytes of text and turn one summary into thousands of billed LLM requests.
    """
    allowance_seconds = max(duration_seconds, _MIN_ALLOWANCE_SECONDS)
    return len(text) <= allowance_seconds * _MAX_CHARS_PER_SECOND
