"""Tests for the rules that decide whether a video can be summarized."""

import pytest

from vidbrief.domain.eligibility import ensure_summarizable, is_plausible_transcript
from vidbrief.domain.errors import (
    LiveStreamNotSupportedError,
    VideoDurationUnknownError,
    VideoTooLongError,
)
from vidbrief.domain.models import LiveStatus, VideoMetadata
from vidbrief.domain.video import VideoId

MAX_DURATION = 7200


def _metadata(
    *,
    duration_seconds: int | None = 600,
    live_status: LiveStatus = LiveStatus.NOT_LIVE,
) -> VideoMetadata:
    return VideoMetadata(
        video_id=VideoId("dQw4w9WgXcQ"),
        title="A video",
        duration_seconds=duration_seconds,
        thumbnail_url=None,
        live_status=live_status,
    )


@pytest.mark.parametrize("live_status", [LiveStatus.NOT_LIVE, LiveStatus.WAS_LIVE])
def test_accepts_finished_videos_within_the_limit(live_status: LiveStatus) -> None:
    ensure_summarizable(_metadata(live_status=live_status), MAX_DURATION)


def test_accepts_a_video_exactly_at_the_limit() -> None:
    ensure_summarizable(_metadata(duration_seconds=MAX_DURATION), MAX_DURATION)


def test_rejects_a_video_over_the_limit() -> None:
    with pytest.raises(VideoTooLongError) as exc_info:
        ensure_summarizable(_metadata(duration_seconds=MAX_DURATION + 1), MAX_DURATION)

    assert exc_info.value.max_duration_seconds == MAX_DURATION


@pytest.mark.parametrize(
    "live_status", [LiveStatus.IS_LIVE, LiveStatus.IS_UPCOMING, LiveStatus.POST_LIVE]
)
def test_rejects_streams_that_have_not_finished(live_status: LiveStatus) -> None:
    with pytest.raises(LiveStreamNotSupportedError) as exc_info:
        ensure_summarizable(_metadata(duration_seconds=None, live_status=live_status), MAX_DURATION)

    assert exc_info.value.reason == live_status.value


def test_rejects_a_video_with_unknown_duration() -> None:
    with pytest.raises(VideoDurationUnknownError):
        ensure_summarizable(_metadata(duration_seconds=None), MAX_DURATION)


class TestPlausibleTranscript:
    def test_accepts_up_to_forty_characters_per_second(self) -> None:
        assert is_plausible_transcript("x" * 40 * 600, duration_seconds=600)

    def test_rejects_text_longer_than_the_video_could_hold(self) -> None:
        assert not is_plausible_transcript("x" * (40 * 600 + 1), duration_seconds=600)

    def test_gives_very_short_videos_a_minute_of_allowance(self) -> None:
        assert is_plausible_transcript("x" * 40 * 60, duration_seconds=5)
        assert not is_plausible_transcript("x" * (40 * 60 + 1), duration_seconds=5)
