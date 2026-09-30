"""Tests for turning YouTube's json3 caption format into plain transcript text."""

import json
from typing import Any

import pytest

from vidbrief.adapters.json3_captions import parse_json3
from vidbrief.domain.errors import CaptionsUnavailableError


def _document(*events: dict[str, Any]) -> bytes:
    return json.dumps({"wireMagic": "pb3", "events": list(events)}).encode()


def _cue(*texts: str) -> dict[str, Any]:
    return {"tStartMs": 0, "segs": [{"utf8": text} for text in texts]}


def test_joins_manual_cues_and_flattens_line_breaks() -> None:
    raw = _document(
        _cue("All right, so here we are, in front of the\nelephants"),
        _cue("the cool thing about these guys is that they\nhave really..."),
    )

    assert parse_json3(raw) == (
        "All right, so here we are, in front of the elephants "
        "the cool thing about these guys is that they have really..."
    )


def test_joins_word_level_segments_of_automatic_captions() -> None:
    raw = _document(
        {"tStartMs": 0, "dDurationMs": 211879, "id": 1, "wpWinPosId": 1},
        _cue("[Music]"),
        {"tStartMs": 18790, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        _cue("We're", " no", " strangers", " to"),
        {"tStartMs": 21790, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        _cue("love.", " You", " know"),
    )

    assert parse_json3(raw) == "We're no strangers to love. You know"


@pytest.mark.parametrize("annotation", ["[Music]", "[Música]", " [Applause] ", "[音楽]"])
def test_drops_cues_that_are_only_sound_annotations(annotation: str) -> None:
    raw = _document(_cue("Hello"), _cue(annotation), _cue("world"))

    assert parse_json3(raw) == "Hello world"


def test_keeps_annotations_that_share_a_cue_with_speech() -> None:
    raw = _document(_cue("[Applause] thank you"))

    assert parse_json3(raw) == "[Applause] thank you"


def test_skips_events_and_segments_with_unexpected_shapes() -> None:
    raw = _document(
        {"segs": "not a list"},
        {"segs": [{"utf8": 42}, "text", {"utf8": "kept"}]},
    )
    document = json.loads(raw)
    document["events"].append("not an event")

    assert parse_json3(json.dumps(document).encode()) == "kept"


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"\xff\xfe\x00", b"[]", b'{"events": 3}', b"{}"],
)
def test_rejects_malformed_documents(raw: bytes) -> None:
    with pytest.raises(CaptionsUnavailableError) as exc_info:
        parse_json3(raw)

    assert exc_info.value.reason == "malformed"


@pytest.mark.parametrize(
    "raw",
    [_document(), _document(_cue("[Music]"), _cue("  "), {"tStartMs": 0})],
)
def test_rejects_documents_without_speech(raw: bytes) -> None:
    with pytest.raises(CaptionsUnavailableError) as exc_info:
        parse_json3(raw)

    assert exc_info.value.reason == "empty"
