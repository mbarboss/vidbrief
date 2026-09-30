"""Checks caption selection and download against YouTube itself (opt-in, needs network)."""

import pytest

from vidbrief.adapters.ytdlp_captions import YtDlpCaptionProvider
from vidbrief.adapters.ytdlp_metadata import YtDlpMetadataProvider
from vidbrief.domain.captions import select_caption_track
from vidbrief.domain.models import CaptionKind, CaptionTrack, Transcript, TranscriptSource
from vidbrief.domain.video import VideoId

pytestmark = pytest.mark.integration

TIMEOUT_SECONDS = 30.0


def _transcribe_from_captions(video_id: VideoId) -> Transcript:
    metadata = YtDlpMetadataProvider(socket_timeout_seconds=TIMEOUT_SECONDS).fetch_metadata(
        video_id
    )
    track = select_caption_track(metadata)
    assert track is not None
    return YtDlpCaptionProvider(socket_timeout_seconds=TIMEOUT_SECONDS).fetch_captions(
        video_id, track
    )


def test_uses_manual_captions_when_available() -> None:
    # "Me at the zoo" has uploader-provided English captions and no speech-recognition track.
    transcript = _transcribe_from_captions(VideoId("jNQXAC9IVRw"))

    assert transcript.source is TranscriptSource.MANUAL_CAPTIONS
    assert transcript.language == "en"
    assert "elephants" in transcript.text


def test_prefers_manual_captions_in_the_original_language() -> None:
    # This music video has manual captions in several languages plus an "en-orig" ASR track.
    video_id = VideoId("dQw4w9WgXcQ")
    metadata = YtDlpMetadataProvider(socket_timeout_seconds=TIMEOUT_SECONDS).fetch_metadata(
        video_id
    )

    track = select_caption_track(metadata)

    assert metadata.original_language == "en"
    assert track is not None
    assert track.kind is CaptionKind.MANUAL
    assert track.language == "en"
    transcript = _transcribe_from_captions(video_id)
    assert "never gonna give you up" in transcript.text.lower()


def test_downloads_automatic_speech_recognition_captions() -> None:
    track = CaptionTrack("en-orig", CaptionKind.AUTO)

    transcript = YtDlpCaptionProvider(socket_timeout_seconds=TIMEOUT_SECONDS).fetch_captions(
        VideoId("dQw4w9WgXcQ"), track
    )

    assert transcript.source is TranscriptSource.AUTO_CAPTIONS
    assert transcript.language == "en"
    assert "strangers" in transcript.text.lower()
    assert "[Music]" not in transcript.text
