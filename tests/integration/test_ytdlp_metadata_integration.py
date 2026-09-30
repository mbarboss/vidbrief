"""Checks the yt-dlp metadata adapter against YouTube itself (opt-in, needs network)."""

import pytest

from vidbrief.adapters.ytdlp_metadata import YtDlpMetadataProvider
from vidbrief.domain.errors import VideoUnavailableError
from vidbrief.domain.models import LiveStatus
from vidbrief.domain.video import VideoId

pytestmark = pytest.mark.integration

# "Me at the zoo": the first video ever uploaded, short and very unlikely to disappear.
STABLE_VIDEO_ID = VideoId("jNQXAC9IVRw")


def test_fetches_metadata_for_a_public_video() -> None:
    metadata = YtDlpMetadataProvider(socket_timeout_seconds=30.0).fetch_metadata(STABLE_VIDEO_ID)

    assert metadata.video_id == STABLE_VIDEO_ID
    assert metadata.title == "Me at the zoo"
    assert metadata.duration_seconds == 19
    assert metadata.live_status is LiveStatus.NOT_LIVE
    assert metadata.thumbnail_url is not None
    assert "en" in metadata.caption_languages + metadata.auto_caption_languages


def test_reports_a_missing_video_as_unavailable() -> None:
    with pytest.raises(VideoUnavailableError):
        YtDlpMetadataProvider(socket_timeout_seconds=30.0).fetch_metadata(VideoId("aaaaaaaaaaa"))
