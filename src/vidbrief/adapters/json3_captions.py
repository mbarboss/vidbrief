"""Parser for YouTube's ``json3`` caption format."""

import json
import re
from typing import Any

from vidbrief.domain.errors import CaptionsUnavailableError

# Cues such as "[Music]" or "[Applause]" describe sounds, not speech, and only add noise to
# the summary. Annotations that share a cue with speech are kept.
_SOUND_ANNOTATION_RE = re.compile(r"\[[^\[\]]*\]")
_WHITESPACE_RE = re.compile(r"\s+")


def parse_json3(raw: bytes) -> str:
    """Return the spoken text of a json3 caption document as a single string.

    Raises:
        CaptionsUnavailableError: ``"malformed"`` if the document cannot be read, or
            ``"empty"`` if it contains no speech.
    """
    try:
        document = json.loads(raw)
    except ValueError:
        raise CaptionsUnavailableError("malformed") from None
    events = document.get("events") if isinstance(document, dict) else None
    if not isinstance(events, list):
        raise CaptionsUnavailableError("malformed")

    cues = [cue for event in events if (cue := _cue_text(event))]
    if not cues:
        raise CaptionsUnavailableError("empty")
    return " ".join(cues)


def _cue_text(event: Any) -> str:
    segments = event.get("segs") if isinstance(event, dict) else None
    if not isinstance(segments, list):
        return ""
    text = "".join(
        segment["utf8"]
        for segment in segments
        if isinstance(segment, dict) and isinstance(segment.get("utf8"), str)
    )
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return "" if _SOUND_ANNOTATION_RE.fullmatch(text) else text
