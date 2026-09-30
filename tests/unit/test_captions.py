"""Tests for choosing which caption track to turn into a transcript."""

import pytest

from vidbrief.domain.captions import select_caption_track
from vidbrief.domain.models import (
    CaptionKind,
    CaptionTrack,
    LiveStatus,
    VideoMetadata,
)
from vidbrief.domain.video import VideoId

MANUAL = CaptionKind.MANUAL
AUTO = CaptionKind.AUTO


def _metadata(
    *,
    original: str | None,
    manual: tuple[str, ...] = (),
    auto: tuple[str, ...] = (),
) -> VideoMetadata:
    return VideoMetadata(
        video_id=VideoId("dQw4w9WgXcQ"),
        title="A video",
        duration_seconds=600,
        thumbnail_url=None,
        live_status=LiveStatus.NOT_LIVE,
        caption_languages=manual,
        auto_caption_languages=auto,
        original_language=original,
    )


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        pytest.param(
            _metadata(original="en", manual=("de", "en"), auto=("en", "en-orig")),
            CaptionTrack("en", MANUAL),
            id="manual-in-original-language-wins",
        ),
        pytest.param(
            _metadata(original="en", manual=("de", "en-US")),
            CaptionTrack("en-US", MANUAL),
            id="manual-matches-on-primary-subtag",
        ),
        pytest.param(
            _metadata(original="en", manual=("en-GB", "en-US")),
            CaptionTrack("en-GB", MANUAL),
            id="manual-regional-variants-are-deterministic",
        ),
        pytest.param(
            _metadata(original="en", manual=("de",), auto=("de", "en", "en-orig", "pt-BR")),
            CaptionTrack("en-orig", AUTO),
            id="original-speech-recognition-before-foreign-manual",
        ),
        pytest.param(
            _metadata(original="en", auto=("en", "pt-BR")),
            CaptionTrack("en", AUTO),
            id="auto-without-orig-suffix",
        ),
        pytest.param(
            _metadata(original="en-US", auto=("en-orig", "pt-BR")),
            CaptionTrack("en-orig", AUTO),
            id="auto-matches-on-primary-subtag",
        ),
        pytest.param(
            _metadata(original="ja", manual=("en", "es"), auto=("en", "es")),
            CaptionTrack("en", MANUAL),
            id="foreign-manual-prefers-english",
        ),
        pytest.param(
            _metadata(original="ja", manual=("es", "fr")),
            CaptionTrack("es", MANUAL),
            id="foreign-manual-falls-back-to-first",
        ),
        pytest.param(
            _metadata(original=None, manual=("de", "en")),
            CaptionTrack("en", MANUAL),
            id="unknown-original-uses-manual",
        ),
        pytest.param(
            _metadata(original=None, auto=("en", "pt-BR")),
            None,
            id="unknown-original-ignores-translated-auto",
        ),
        pytest.param(
            _metadata(original="ja", auto=("en", "pt-BR")),
            None,
            id="translated-auto-is-never-used",
        ),
        pytest.param(_metadata(original="en"), None, id="no-captions"),
    ],
)
def test_selects_the_best_track(metadata: VideoMetadata, expected: CaptionTrack | None) -> None:
    assert select_caption_track(metadata) == expected


@pytest.mark.parametrize(
    ("track", "expected"),
    [
        (CaptionTrack("en-orig", AUTO), "en"),
        (CaptionTrack("pt-BR", MANUAL), "pt-BR"),
        (CaptionTrack("en", AUTO), "en"),
    ],
)
def test_content_language_drops_the_orig_marker(track: CaptionTrack, expected: str) -> None:
    assert track.content_language == expected
