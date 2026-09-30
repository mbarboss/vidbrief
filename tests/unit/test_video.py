"""Tests for YouTube URL parsing and canonicalization."""

from dataclasses import FrozenInstanceError

import pytest

from vidbrief.domain.errors import InvalidVideoUrlError, VidbriefError
from vidbrief.domain.video import VideoId, parse_youtube_url

VIDEO_ID = "dQw4w9WgXcQ"
CANONICAL_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


class TestVideoId:
    def test_accepts_eleven_url_safe_characters(self) -> None:
        assert VideoId("a-b_c-d_e-f").value == "a-b_c-d_e-f"

    @pytest.mark.parametrize(
        "value",
        ["", "short", "dQw4w9WgXcQQ", "dQw4w9WgXc!", "dQw4w9WgXc ", "dQw4w9WgXcQ\n"],
    )
    def test_rejects_malformed_values(self, value: str) -> None:
        with pytest.raises(ValueError, match="invalid video id"):
            VideoId(value)

    def test_builds_canonical_url(self) -> None:
        assert VideoId(VIDEO_ID).canonical_url == CANONICAL_URL

    def test_is_immutable(self) -> None:
        video_id = VideoId(VIDEO_ID)
        with pytest.raises(FrozenInstanceError):
            video_id.value = "aaaaaaaaaaa"  # type: ignore[misc]


class TestParseYoutubeUrlAccepts:
    @pytest.mark.parametrize(
        "url",
        [
            f"https://www.youtube.com/watch?v={VIDEO_ID}",
            f"http://youtube.com/watch?v={VIDEO_ID}",
            f"https://m.youtube.com/watch?v={VIDEO_ID}",
            f"https://www.youtube.com/watch?v={VIDEO_ID}&t=42s&list=PLabc",
            f"https://www.youtube.com/watch?feature=share&v={VIDEO_ID}",
            f"https://www.youtube.com/watch?v={VIDEO_ID}#t=10",
            f"https://youtu.be/{VIDEO_ID}",
            f"https://youtu.be/{VIDEO_ID}?si=abc123&t=10",
            f"https://www.youtube.com/shorts/{VIDEO_ID}",
            f"https://www.youtube.com/shorts/{VIDEO_ID}/",
            f"https://www.youtube.com/live/{VIDEO_ID}?feature=share",
            f"https://www.youtube.com/embed/{VIDEO_ID}",
            f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
            f"HTTPS://WWW.YOUTUBE.COM/watch?v={VIDEO_ID}",
            f"  https://youtu.be/{VIDEO_ID}  \n",
        ],
    )
    def test_supported_formats(self, url: str) -> None:
        assert parse_youtube_url(url) == VideoId(VIDEO_ID)

    @pytest.mark.parametrize(
        "url",
        [
            f"youtube.com/watch?v={VIDEO_ID}",
            f"www.youtube.com/watch?v={VIDEO_ID}",
            f"youtu.be/{VIDEO_ID}",
            f"youtube.com/shorts/{VIDEO_ID}",
        ],
    )
    def test_scheme_less_urls_default_to_https(self, url: str) -> None:
        assert parse_youtube_url(url).canonical_url == CANONICAL_URL


class TestParseYoutubeUrlRejects:
    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
            "not a url",
            "https://",
            "//www.youtube.com/watch?v=dQw4w9WgXcQ",
            f"ftp://www.youtube.com/watch?v={VIDEO_ID}",
            "file:///etc/passwd",
            "javascript:alert(1)",
            f"https://evil.com/watch?v={VIDEO_ID}",
            f"https://youtube.com.evil.com/watch?v={VIDEO_ID}",
            f"https://evilyoutube.com/watch?v={VIDEO_ID}",
            f"https://www.youtube.com./watch?v={VIDEO_ID}",
            f"https://www.y\u043eutube.com/watch?v={VIDEO_ID}",
            f"https://user:pass@www.youtube.com/watch?v={VIDEO_ID}",  # pragma: allowlist secret
            f"https://www.youtube.com@evil.com/watch?v={VIDEO_ID}",
            f"https://www.youtube.com\\@evil.com/watch?v={VIDEO_ID}",
            f"https://www.youtube.com:443/watch?v={VIDEO_ID}",
            f"https://www.youtube.com:8443/watch?v={VIDEO_ID}",
            f"https://127.0.0.1/watch?v={VIDEO_ID}",
            f"https://[::1]/watch?v={VIDEO_ID}",
            "https://[::1/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9\nWgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXc",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXc!",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ%00",
            "https://www.youtube.com/watch",
            "https://www.youtube.com/watch?v=",
            f"https://www.youtube.com/watch?v=aaaaaaaaaaa&v={VIDEO_ID}",
            "https://www.youtube.com/",
            "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw",
            "https://www.youtube.com/playlist?list=PLabc",
            "https://youtu.be/",
            f"https://youtu.be/{VIDEO_ID}/extra",
            "https://www.youtube.com/shorts/",
            f"https://www.youtube.com/shorts/{VIDEO_ID}/extra",
            f"https://www.youtube.com/shorts//{VIDEO_ID}",
        ],
    )
    def test_invalid_urls(self, url: str) -> None:
        with pytest.raises(InvalidVideoUrlError):
            parse_youtube_url(url)

    @pytest.mark.parametrize(
        ("url", "reason"),
        [
            ("", "empty"),
            ("https://youtu.be/" + "a" * 2100, "too_long"),
            ("https://youtu.be/dQw4w9\tWgXcQ", "invalid_characters"),
            (f"ftp://youtu.be/{VIDEO_ID}", "scheme_not_allowed"),
            (f"https://user@youtu.be/{VIDEO_ID}", "userinfo_not_allowed"),
            (f"https://youtu.be:443/{VIDEO_ID}", "port_not_allowed"),
            (f"https://evil.com/{VIDEO_ID}", "host_not_allowed"),
            ("https://www.youtube.com/playlist?list=PLabc", "invalid_video_id"),
        ],
    )
    def test_reports_a_safe_reason_code(self, url: str, reason: str) -> None:
        with pytest.raises(InvalidVideoUrlError) as exc_info:
            parse_youtube_url(url)
        assert exc_info.value.reason == reason

    def test_error_never_echoes_user_input(self) -> None:
        with pytest.raises(InvalidVideoUrlError) as exc_info:
            parse_youtube_url("https://evil.com/<script>alert(1)</script>")
        error = exc_info.value
        assert isinstance(error, VidbriefError)
        assert error.user_message == "Please enter a valid YouTube video link."
        for text in (str(error), error.user_message):
            assert "evil" not in text
            assert "script" not in text
