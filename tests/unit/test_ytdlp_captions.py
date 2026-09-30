"""Tests for the yt-dlp caption adapter, using a fake in place of ``yt_dlp.YoutubeDL``."""

import json
import re

import pytest
from yt_dlp.utils import DownloadError

from tests.unit.ytdlp_fake import FakeYoutubeDL
from vidbrief.adapters.ytdlp_captions import YtDlpCaptionProvider
from vidbrief.domain.errors import CaptionsUnavailableError
from vidbrief.domain.models import CaptionKind, CaptionTrack, Transcript, TranscriptSource
from vidbrief.domain.ports import CaptionProvider
from vidbrief.domain.video import VideoId

VIDEO_ID = VideoId("jNQXAC9IVRw")
MANUAL_EN = CaptionTrack("en", CaptionKind.MANUAL)
AUTO_EN_ORIG = CaptionTrack("en-orig", CaptionKind.AUTO)
CAPTIONS = json.dumps({"events": [{"segs": [{"utf8": "in front of the\nelephants"}]}]}).encode()


def _provider(fake: FakeYoutubeDL, **kwargs: int) -> YtDlpCaptionProvider:
    return YtDlpCaptionProvider(socket_timeout_seconds=30.0, ydl_factory=fake, **kwargs)


def _fake_writing(track: CaptionTrack, content: bytes = CAPTIONS) -> FakeYoutubeDL:
    return FakeYoutubeDL(files={f"{VIDEO_ID.value}.{track.language}.json3": content})


def test_satisfies_the_caption_port() -> None:
    provider: CaptionProvider = YtDlpCaptionProvider(socket_timeout_seconds=30.0)

    assert provider is not None


class TestTranscript:
    def test_builds_a_transcript_from_manual_captions(self) -> None:
        transcript = _provider(_fake_writing(MANUAL_EN)).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert transcript == Transcript(
            video_id=VIDEO_ID,
            language="en",
            source=TranscriptSource.MANUAL_CAPTIONS,
            text="in front of the elephants",
        )

    def test_builds_a_transcript_from_automatic_captions(self) -> None:
        transcript = _provider(_fake_writing(AUTO_EN_ORIG)).fetch_captions(VIDEO_ID, AUTO_EN_ORIG)

        assert transcript.language == "en"
        assert transcript.source is TranscriptSource.AUTO_CAPTIONS


class TestRequest:
    def test_downloads_only_captions_for_the_canonical_url(self) -> None:
        fake = _fake_writing(MANUAL_EN)

        _provider(fake).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert fake.extracted == [(VIDEO_ID.canonical_url, True)]
        assert fake.options["skip_download"] is True
        assert fake.options["subtitlesformat"] == "json3"
        assert fake.options["outtmpl"] == {"default": f"{VIDEO_ID.value}.%(ext)s"}
        assert "cookiefile" not in fake.options

    @pytest.mark.parametrize(
        ("track", "manual", "auto"),
        [(MANUAL_EN, True, False), (AUTO_EN_ORIG, False, True)],
    )
    def test_requests_only_the_selected_kind(
        self, track: CaptionTrack, manual: bool, auto: bool
    ) -> None:
        fake = _fake_writing(track)

        _provider(fake).fetch_captions(VIDEO_ID, track)

        assert fake.options["writesubtitles"] is manual
        assert fake.options["writeautomaticsub"] is auto

    def test_language_filter_matches_only_the_exact_code(self) -> None:
        fake = _fake_writing(AUTO_EN_ORIG)

        _provider(fake).fetch_captions(VIDEO_ID, AUTO_EN_ORIG)

        [pattern] = fake.options["subtitleslangs"]
        # yt-dlp treats each entry as a regex and appends "$" before matching.
        matches = [
            code
            for code in ("en-orig", "en", "xen-orig", "en-orig-x", "enXorig")
            if re.match(pattern + "$", code)
        ]
        assert matches == ["en-orig"]

    def test_language_filter_cannot_trigger_special_keywords(self) -> None:
        track = CaptionTrack("all", CaptionKind.MANUAL)
        fake = _fake_writing(track)

        _provider(fake).fetch_captions(VIDEO_ID, track)

        assert fake.options["subtitleslangs"] != ["all"]


class TestTemporaryFiles:
    def test_removes_the_working_directory_after_success(self) -> None:
        fake = _fake_writing(MANUAL_EN)

        _provider(fake).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert not fake.workdir.exists()

    def test_removes_the_working_directory_after_failure(self) -> None:
        fake = _fake_writing(MANUAL_EN, content=b"not json")

        with pytest.raises(CaptionsUnavailableError):
            _provider(fake).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert not fake.workdir.exists()


class TestFailures:
    def test_reports_download_errors(self) -> None:
        original = DownloadError("ERROR: Unable to download video subtitles")
        fake = FakeYoutubeDL(original)

        with pytest.raises(CaptionsUnavailableError) as exc_info:
            _provider(fake).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert exc_info.value.reason == "download_failed"
        assert exc_info.value.__cause__ is original

    def test_reports_a_missing_caption_file(self) -> None:
        with pytest.raises(CaptionsUnavailableError) as exc_info:
            _provider(FakeYoutubeDL()).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert exc_info.value.reason == "not_downloaded"

    def test_reports_ambiguous_output(self) -> None:
        fake = FakeYoutubeDL(
            files={"a.en.json3": CAPTIONS, "b.en.json3": CAPTIONS},
        )

        with pytest.raises(CaptionsUnavailableError) as exc_info:
            _provider(fake).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert exc_info.value.reason == "not_downloaded"

    def test_rejects_oversized_caption_files(self) -> None:
        fake = _fake_writing(MANUAL_EN)

        with pytest.raises(CaptionsUnavailableError) as exc_info:
            _provider(fake, max_caption_bytes=len(CAPTIONS) - 1).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert exc_info.value.reason == "too_large"

    def test_reports_unparseable_captions(self) -> None:
        fake = _fake_writing(MANUAL_EN, content=b"not json")

        with pytest.raises(CaptionsUnavailableError) as exc_info:
            _provider(fake).fetch_captions(VIDEO_ID, MANUAL_EN)

        assert exc_info.value.reason == "malformed"
