"""Markdown rendering of a finished summary, safe for untrusted titles and LLM output."""

from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES
from vidbrief.domain.models import TranscriptSource
from vidbrief.services.inline_markdown import escape_markdown, to_inline_markdown
from vidbrief.services.pipeline import PipelineResult

_SOURCE_LABELS = {
    TranscriptSource.MANUAL_CAPTIONS: "captions written by the uploader",
    TranscriptSource.AUTO_CAPTIONS: "YouTube's automatic captions",
    TranscriptSource.SPEECH_TO_TEXT: "a speech-to-text transcript",
}
_UNTITLED = "Untitled video"


def to_markdown(result: PipelineResult) -> str:
    """Render ``result`` as a Markdown document.

    Every untrusted field is flattened to one line and stripped of control and bidi
    characters, so it can inject neither Markdown structure, links or HTML nor terminal
    escape sequences. The summary keeps its bold, italics and code; the title is fully
    escaped.
    """
    summary = result.summary
    title = escape_markdown(result.metadata.title) or _UNTITLED
    language = SUPPORTED_SUMMARY_LANGUAGES.get(summary.language, summary.language)
    source = _SOURCE_LABELS[result.transcript_source]
    lines = [
        f"# {title}",
        "",
        f"<{result.metadata.video_id.canonical_url}>",
        "",
        "## TL;DR",
        "",
        to_inline_markdown(summary.tldr),
        "",
        "## Key points",
        "",
        *(f"- {to_inline_markdown(point)}" for point in summary.key_points),
        "",
        "---",
        "",
        f"*Summary in {escape_markdown(language)}, from {source}.*",
    ]
    return "\n".join(lines) + "\n"
