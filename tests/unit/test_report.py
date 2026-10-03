"""Tests for the Markdown report of a pipeline result."""

from dataclasses import replace

import pytest

from vidbrief.domain.models import (
    LiveStatus,
    Summary,
    TranscriptSource,
    VideoMetadata,
)
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import PipelineResult
from vidbrief.services.report import to_markdown

VIDEO_ID = VideoId("jNQXAC9IVRw")
RESULT = PipelineResult(
    metadata=VideoMetadata(
        video_id=VIDEO_ID,
        title="Me at the zoo",
        duration_seconds=19,
        thumbnail_url=None,
        live_status=LiveStatus.NOT_LIVE,
    ),
    transcript_source=TranscriptSource.MANUAL_CAPTIONS,
    summary=Summary(VIDEO_ID, "pt-BR", "Um vídeo curto.", ("Elefantes", "Trombas longas")),
)


def _with(title: str | None = None, tldr: str | None = None, points: tuple[str, ...] = ()) -> str:
    metadata = RESULT.metadata if title is None else replace(RESULT.metadata, title=title)
    summary = replace(
        RESULT.summary,
        tldr=RESULT.summary.tldr if tldr is None else tldr,
        key_points=points or RESULT.summary.key_points,
    )
    return to_markdown(replace(RESULT, metadata=metadata, summary=summary))


def test_renders_title_link_tldr_points_and_footer() -> None:
    assert to_markdown(RESULT) == (
        "# Me at the zoo\n"
        "\n"
        "<https://www.youtube.com/watch?v=jNQXAC9IVRw>\n"
        "\n"
        "## TL;DR\n"
        "\n"
        "Um vídeo curto.\n"
        "\n"
        "## Key points\n"
        "\n"
        "- Elefantes\n"
        "- Trombas longas\n"
        "\n"
        "---\n"
        "\n"
        "*Summary in Brazilian Portuguese, from captions written by the uploader.*\n"
    )


@pytest.mark.parametrize(
    ("source", "label"),
    [
        (TranscriptSource.AUTO_CAPTIONS, "from YouTube's automatic captions"),
        (TranscriptSource.SPEECH_TO_TEXT, "from a speech-to-text transcript"),
    ],
)
def test_names_where_the_transcript_came_from(source: TranscriptSource, label: str) -> None:
    assert label in to_markdown(replace(RESULT, transcript_source=source))


def test_escapes_markdown_and_html_in_untrusted_text() -> None:
    markdown = _with(
        title="<script>alert(1)</script> [x](javascript:alert(1)) **bold** `code`",
        tldr="# Heading | table ~strike~ _em_",
        points=("<img src=x onerror=alert(1)>",),
    )

    assert "<script>" not in markdown
    assert "\\<script\\>" in markdown
    assert "\\[x\\](javascript:alert(1))" in markdown
    assert "\\*\\*bold\\*\\*" in markdown
    assert "\\`code\\`" in markdown
    assert "\\# Heading \\| table \\~strike\\~ *em*" in markdown
    assert "- \\<img src=x onerror=alert(1)\\>" in markdown


def test_keeps_the_formatting_the_summary_may_use_but_not_in_the_title() -> None:
    markdown = _with(
        title="**Not bold**",
        tldr="A **key** idea with *nuance*.",
        points=("Run `uv sync`", "2) numbered"),
    )

    assert "# \\*\\*Not bold\\*\\*\n" in markdown
    assert "\nA **key** idea with *nuance*.\n" in markdown
    assert "- Run `uv sync`\n" in markdown
    assert "- 2\\) numbered\n" in markdown


def test_removes_control_characters() -> None:
    markdown = _with(title="Evil\x1b[31mRed\x07‮Title")

    assert "\x1b" not in markdown
    assert "\x07" not in markdown
    assert "‮" not in markdown
    assert "# Evil\\[31mRedTitle\n" in markdown


def test_keeps_every_field_on_one_line() -> None:
    markdown = _with(title="Line one\n## Injected", tldr="First\r\n\r\nSecond", points=("a\nb",))

    assert "# Line one \\#\\# Injected\n" in markdown
    assert "\nFirst Second\n" in markdown
    assert "- a b\n" in markdown


@pytest.mark.parametrize(
    ("point", "rendered"),
    [("- nested", "- \\- nested"), ("+ plus", "- \\+ plus"), ("1. first", "- 1\\. first")],
)
def test_escapes_list_markers_at_the_start_of_a_point(point: str, rendered: str) -> None:
    assert f"{rendered}\n" in _with(points=(point,))


def test_uses_a_placeholder_for_a_blank_title() -> None:
    assert _with(title=" \x00 ").startswith("# Untitled video\n")
