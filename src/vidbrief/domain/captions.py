"""Choice of the caption track that best represents what is said in a video."""

from collections.abc import Iterable

from vidbrief.domain.models import (
    ORIGINAL_TRACK_SUFFIX,
    CaptionKind,
    CaptionTrack,
    VideoMetadata,
)

_FALLBACK_LANGUAGE = "en"


def select_caption_track(metadata: VideoMetadata) -> CaptionTrack | None:
    """Pick the caption track to use as the transcript, or ``None`` to transcribe audio.

    Preference order:

    1. Manual captions in the spoken language.
    2. YouTube's speech recognition in the spoken language.
    3. Manual captions in another language, English first.

    Machine-translated automatic tracks are never chosen: translating from the original
    transcript is left to the summarizer, which does it far better.
    """
    original = metadata.original_language
    if original:
        manual = _find_language(metadata.caption_languages, original)
        if manual:
            return CaptionTrack(manual, CaptionKind.MANUAL)
        auto = _find_original_auto_track(metadata.auto_caption_languages, original)
        if auto:
            return CaptionTrack(auto, CaptionKind.AUTO)

    if not metadata.caption_languages:
        return None
    fallback = _find_language(metadata.caption_languages, _FALLBACK_LANGUAGE)
    return CaptionTrack(fallback or metadata.caption_languages[0], CaptionKind.MANUAL)


def _find_language(codes: Iterable[str], wanted: str) -> str | None:
    codes = sorted(codes)
    if wanted in codes:
        return wanted
    primary = _primary_subtag(wanted)
    return next((code for code in codes if _primary_subtag(code) == primary), None)


def _find_original_auto_track(codes: tuple[str, ...], original: str) -> str | None:
    primary = _primary_subtag(original)
    candidates = (
        f"{original}{ORIGINAL_TRACK_SUFFIX}",
        original,
        f"{primary}{ORIGINAL_TRACK_SUFFIX}",
        primary,
    )
    return next((code for code in candidates if code in codes), None)


def _primary_subtag(code: str) -> str:
    return code.split("-", 1)[0].lower()
