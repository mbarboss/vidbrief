"""Tests for the yt-dlp audio downloader, using a fake in place of ``yt_dlp.YoutubeDL``."""

from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from tests.unit.ytdlp_fake import FakeYoutubeDL
from vidbrief.adapters.ytdlp_audio import YtDlpAudioDownloader
from vidbrief.domain.errors import AudioProcessingError, ExternalServiceError
from vidbrief.domain.video import VideoId

VIDEO_ID = VideoId("jNQXAC9IVRw")
SOURCE_NAME = f"{VIDEO_ID.value}.source.webm"


def _download(fake: FakeYoutubeDL, workdir: Path, **kwargs: int) -> Path:
    downloader = YtDlpAudioDownloader(socket_timeout_seconds=30.0, ydl_factory=fake, **kwargs)
    return downloader.download(VIDEO_ID, workdir)


def test_returns_the_downloaded_file(tmp_path: Path) -> None:
    fake = FakeYoutubeDL(files={SOURCE_NAME: b"audio"})

    assert _download(fake, tmp_path) == tmp_path / SOURCE_NAME


def test_downloads_audio_only_from_the_canonical_url(tmp_path: Path) -> None:
    fake = FakeYoutubeDL(files={SOURCE_NAME: b"audio"})

    _download(fake, tmp_path, max_download_bytes=1234)

    assert fake.extracted == [(VIDEO_ID.canonical_url, True)]
    assert fake.options["format"] == "bestaudio"
    assert fake.options["skip_download"] is False
    assert fake.options["max_filesize"] == 1234
    assert fake.options["noplaylist"] is True
    assert fake.options["paths"] == {"home": str(tmp_path), "temp": str(tmp_path)}
    assert fake.options["outtmpl"] == {"default": f"{VIDEO_ID.value}.source.%(ext)s"}
    assert "cookiefile" not in fake.options
    assert "postprocessors" not in fake.options


def test_ignores_leftover_partial_files(tmp_path: Path) -> None:
    fake = FakeYoutubeDL(files={SOURCE_NAME: b"audio", f"{SOURCE_NAME}.part": b"au"})

    assert _download(fake, tmp_path) == tmp_path / SOURCE_NAME


@pytest.mark.parametrize(
    "files",
    [
        {},
        {f"{SOURCE_NAME}.part": b"au"},
        {SOURCE_NAME: b"audio", f"{VIDEO_ID.value}.source.m4a": b"audio"},
    ],
    ids=["nothing", "only-partial", "ambiguous"],
)
def test_reports_a_missing_download(tmp_path: Path, files: dict[str, bytes]) -> None:
    # yt-dlp silently skips files above max_filesize, which also lands here.
    with pytest.raises(AudioProcessingError) as exc_info:
        _download(FakeYoutubeDL(files=files), tmp_path)

    assert exc_info.value.reason == "not_downloaded"


def test_translates_download_errors(tmp_path: Path) -> None:
    original = DownloadError("ERROR: [youtube] x: Sign in to confirm you're not a bot.")

    with pytest.raises(ExternalServiceError) as exc_info:
        _download(FakeYoutubeDL(original), tmp_path)

    assert exc_info.value.reason == "bot_check"
    assert exc_info.value.__cause__ is original
