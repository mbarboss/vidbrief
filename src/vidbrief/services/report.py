"""Markdown rendering of a finished summary, safe for untrusted titles and LLM output."""

import re
import unicodedata

from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES
from vidbrief.domain.models import TranscriptSource
from vidbrief.services.pipeline import PipelineResult

_SOURCE_LABELS = {
    TranscriptSource.MANUAL_CAPTIONS: "captions written by the uploader",
    TranscriptSource.AUTO_CAPTIONS: "YouTube's automatic captions",
    TranscriptSource.SPEECH_TO_TEXT: "a speech-to-text transcript",
}
_MARKDOWN_SPECIAL_RE = re.compile(r"([\\`*_\[\]<>#|~])")
_LEADING_LIST_MARKER_RE = re.compile(r"^([-+]|\d+\.)(?=\s|$)")
_UNTITLED = "Untitled video"


def to_markdown(result: PipelineResult) -> str:
    """Render ``result`` as a Markdown document.

    Every untrusted field is flattened to one line, stripped of control and bidi
    characters and escaped, so it can neither inject Markdown structure, links or HTML
    nor terminal escape sequences.
    """
    summary = result.summary
    title = _inline(result.metadata.title) or _UNTITLED
    language = SUPPORTED_SUMMARY_LANGUAGES.get(summary.language, summary.language)
    lines = [
        f"# {title}",
        "",
        f"<{result.metadata.video_id.canonical_url}>",
        "",
        "## TL;DR",
        "",
        _inline(summary.tldr),
        "",
        "## Key points",
        "",
        *(f"- {_inline(point)}" for point in summary.key_points),
        "",
        "---",
        "",
        f"*Summary in {_inline(language)}, from {_SOURCE_LABELS[result.transcript_source]}.*",
    ]
    return "\n".join(lines) + "\n"


def _inline(text: str) -> str:
    # Whitespace is collapsed before control characters are dropped, so a newline becomes
    # a space instead of gluing two words together.
    flat = " ".join(text.split())
    visible = "".join(char for char in flat if not unicodedata.category(char).startswith("C"))
    escaped = _MARKDOWN_SPECIAL_RE.sub(r"\\\1", visible.strip())
    return _LEADING_LIST_MARKER_RE.sub(_escape_marker, escaped)


def _escape_marker(match: re.Match[str]) -> str:
    marker = match.group(1)
    return f"{marker[:-1]}\\." if marker.endswith(".") else f"\\{marker}"
