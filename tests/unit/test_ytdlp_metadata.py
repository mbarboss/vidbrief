"""Tests for the yt-dlp metadata adapter, using a fake in place of ``yt_dlp.YoutubeDL``."""

from typing import Any

import pytest
from yt_dlp.utils import DownloadError, YoutubeDLError

from tests.unit.ytdlp_fake import FakeYoutubeDL
from vidbrief.adapters.ytdlp_metadata import YtDlpMetadataProvider
from vidbrief.domain.errors import (
    ExternalServiceError,
    LiveStreamNotSupportedError,
    VidbriefError,
    VideoUnavailableError,
)
from vidbrief.domain.models import LiveStatus, VideoMetadata
from vidbrief.domain.ports import VideoMetadataProvider
from vidbrief.domain.video import VideoId

VIDEO_ID = VideoId("jNQXAC9IVRw")
THUMBNAIL_URL = "https://i.ytimg.com/vi/jNQXAC9IVRw/maxresdefault.jpg"


def _info(**overrides: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": VIDEO_ID.value,
        "title": "Me at the zoo",
        "duration": 19,
        "thumbnail": THUMBNAIL_URL,
        "live_status": "not_live",
        "subtitles": {"en": [{}], "de": [{}], "live_chat": [{}]},
        "automatic_captions": {"pt-BR": [{}], "en-orig": [{}], "en": [{}]},
    }
    info.update(overrides)
    return info


def _fetch(outcome: dict[str, Any] | Exception | None) -> VideoMetadata:
    provider = YtDlpMetadataProvider(
        socket_timeout_seconds=30.0, ydl_factory=FakeYoutubeDL(outcome)
    )
    return provider.fetch_metadata(VIDEO_ID)


def test_satisfies_the_metadata_port() -> None:
    provider: VideoMetadataProvider = YtDlpMetadataProvider(socket_timeout_seconds=30.0)

    assert provider is not None


class TestRequest:
    def test_only_fetches_the_canonical_url_without_downloading(self) -> None:
        fake = FakeYoutubeDL(_info())

        YtDlpMetadataProvider(socket_timeout_seconds=30.0, ydl_factory=fake).fetch_metadata(
            VIDEO_ID
        )

        assert fake.extracted == [(VIDEO_ID.canonical_url, False)]

    def test_uses_safe_options(self) -> None:
        fake = FakeYoutubeDL(_info())

        YtDlpMetadataProvider(socket_timeout_seconds=12.5, ydl_factory=fake).fetch_metadata(
            VIDEO_ID
        )

        assert fake.options["skip_download"] is True
        assert fake.options["noplaylist"] is True
        assert fake.options["quiet"] is True
        assert fake.options["socket_timeout"] == 12.5
        assert "cookiefile" not in fake.options
        assert "cookiesfrombrowser" not in fake.options


class TestMapping:
    def test_maps_a_regular_video(self) -> None:
        assert _fetch(_info()) == VideoMetadata(
            video_id=VIDEO_ID,
            title="Me at the zoo",
            duration_seconds=19,
            thumbnail_url=THUMBNAIL_URL,
            live_status=LiveStatus.NOT_LIVE,
            caption_languages=("de", "en"),
            auto_caption_languages=("en", "en-orig", "pt-BR"),
            original_language="en",
        )

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"language": "pt-BR"}, "pt-BR"),
            ({"language": None}, "en"),
            ({"language": "../etc"}, "en"),
            ({"language": None, "automatic_captions": {"en": [{}]}}, None),
            ({"language": None, "automatic_captions": {"ja-orig": [{}], "en": [{}]}}, "ja"),
        ],
    )
    def test_detects_the_original_language(
        self, overrides: dict[str, Any], expected: str | None
    ) -> None:
        assert _fetch(_info(**overrides)).original_language == expected

    @pytest.mark.parametrize(
        ("raw_title", "expected"),
        [("  Padded title  ", "Padded title"), (None, ""), (42, "")],
    )
    def test_normalizes_the_title(self, raw_title: object, expected: str) -> None:
        assert _fetch(_info(title=raw_title)).title == expected

    @pytest.mark.parametrize(
        ("raw_duration", "expected"),
        [(19.7, 19), (0, None), (-5, None), (None, None), ("19", None), (True, None)],
    )
    def test_normalizes_the_duration(self, raw_duration: object, expected: int | None) -> None:
        assert _fetch(_info(duration=raw_duration)).duration_seconds == expected

    @pytest.mark.parametrize(
        "raw_thumbnail",
        [
            "http://i.ytimg.com/vi/jNQXAC9IVRw/0.jpg",
            "https://evil.com/vi/jNQXAC9IVRw/0.jpg",
            "https://i.ytimg.com.evil.com/vi/jNQXAC9IVRw/0.jpg",
            "https://user@i.ytimg.com/vi/jNQXAC9IVRw/0.jpg",
            "https://i.ytimg.com:8443/vi/jNQXAC9IVRw/0.jpg",
            "https://[::1/vi/0.jpg",
            "javascript:alert(1)",
            None,
            123,
        ],
    )
    def test_drops_thumbnails_outside_the_image_cdn(self, raw_thumbnail: object) -> None:
        assert _fetch(_info(thumbnail=raw_thumbnail)).thumbnail_url is None

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"live_status": "is_live"}, LiveStatus.IS_LIVE),
            ({"live_status": "is_upcoming"}, LiveStatus.IS_UPCOMING),
            ({"live_status": "was_live"}, LiveStatus.WAS_LIVE),
            ({"live_status": "post_live"}, LiveStatus.POST_LIVE),
            ({"live_status": None, "is_live": True}, LiveStatus.IS_LIVE),
            ({"live_status": None}, LiveStatus.NOT_LIVE),
            ({"live_status": "something_new"}, LiveStatus.NOT_LIVE),
        ],
    )
    def test_maps_the_live_status(self, overrides: dict[str, Any], expected: LiveStatus) -> None:
        assert _fetch(_info(**overrides)).live_status == expected

    def test_keeps_only_well_formed_language_codes(self) -> None:
        metadata = _fetch(
            _info(
                subtitles={"en-US": [{}], "live_chat": [{}], "../etc": [{}], "": [{}]},
                automatic_captions=None,
            )
        )

        assert metadata.caption_languages == ("en-US",)
        assert metadata.auto_caption_languages == ()

    @pytest.mark.parametrize("outcome", [None, _info(id="aaaaaaaaaaa"), _info(id=None)])
    def test_rejects_responses_for_another_video(self, outcome: dict[str, Any] | None) -> None:
        with pytest.raises(ExternalServiceError) as exc_info:
            _fetch(outcome)

        assert exc_info.value.reason == "unexpected_response"


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("message", "error_type", "reason"),
        [
            (
                "ERROR: [youtube] x: Private video. Sign in if you've been granted access",
                VideoUnavailableError,
                "private",
            ),
            (
                "ERROR: [youtube] x: Sign in to confirm your age. This video may be "
                "inappropriate for some users.",
                VideoUnavailableError,
                "age_restricted",
            ),
            (
                "ERROR: [youtube] x: Join this channel to get access to members-only content",
                VideoUnavailableError,
                "members_only",
            ),
            (
                "ERROR: [youtube] x: The uploader has not made this video available in your "
                "country",
                VideoUnavailableError,
                "geo_blocked",
            ),
            (
                "ERROR: [youtube] x: Video unavailable. This video has been removed by the "
                "uploader",
                VideoUnavailableError,
                "removed",
            ),
            ("ERROR: [youtube] x: Video unavailable", VideoUnavailableError, "unavailable"),
            (
                "ERROR: [youtube] x: This video is unavailable",
                VideoUnavailableError,
                "unavailable",
            ),
            (
                "ERROR: [youtube] x: This live event will begin in 3 hours.",
                LiveStreamNotSupportedError,
                "is_upcoming",
            ),
            (
                "ERROR: [youtube] x: Premieres in 2 days",
                LiveStreamNotSupportedError,
                "is_upcoming",
            ),
            (
                "ERROR: [youtube] x: Sign in to confirm "
                "you\N{RIGHT SINGLE QUOTATION MARK}re not a bot.",
                ExternalServiceError,
                "bot_check",
            ),
            (
                "ERROR: [youtube] x: Sign in to confirm you're not a bot.",
                ExternalServiceError,
                "bot_check",
            ),
            (
                "ERROR: [youtube] x: Unable to download API page: <urlopen error timed out>",
                ExternalServiceError,
                "download_failed",
            ),
        ],
    )
    def test_translates_download_errors(
        self, message: str, error_type: type[VidbriefError], reason: str
    ) -> None:
        with pytest.raises(error_type) as exc_info:
            _fetch(DownloadError(message))

        assert exc_info.value.reason == reason
        assert "youtube" not in exc_info.value.user_message.lower()

    def test_translates_other_ytdlp_errors(self) -> None:
        with pytest.raises(ExternalServiceError) as exc_info:
            _fetch(YoutubeDLError("unexpected"))

        assert exc_info.value.reason == "download_failed"

    def test_keeps_the_original_error_for_operators(self) -> None:
        original = DownloadError("ERROR: Private video")

        with pytest.raises(VideoUnavailableError) as exc_info:
            _fetch(original)

        assert exc_info.value.__cause__ is original
