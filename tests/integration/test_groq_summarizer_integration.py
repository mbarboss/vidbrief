"""Summarizes a fixed transcript with Groq (opt-in, needs network and GROQ_API_KEY)."""

import pytest

from vidbrief.adapters.groq_summarizer import GroqSummarizer
from vidbrief.config import get_settings
from vidbrief.domain.models import Transcript, TranscriptSource
from vidbrief.domain.video import VideoId

pytestmark = pytest.mark.integration

TRANSCRIPT = (
    "Alright, so here we are in front of the elephants. The cool thing about these guys is "
    "that they have really, really, really long trunks. And that's cool. And that's pretty "
    "much all there is to say."
)


def test_summarizes_a_short_transcript_in_portuguese() -> None:
    summarizer = GroqSummarizer.from_settings(get_settings())
    transcript = Transcript(
        video_id=VideoId("jNQXAC9IVRw"),
        language="en",
        source=TranscriptSource.MANUAL_CAPTIONS,
        text=TRANSCRIPT,
    )

    summary = summarizer.summarize(transcript, "pt-BR")

    assert summary.language == "pt-BR"
    assert summary.tldr
    assert summary.key_points
    assert "elefante" in f"{summary.tldr} {' '.join(summary.key_points)}".lower()
