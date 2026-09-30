"""Speech-to-text backed by Groq's hosted Whisper models."""

import logging
import re
import time
from collections.abc import Callable, Sequence
from typing import Literal, Protocol, Self

from groq import Omit, omit

from vidbrief.adapters.groq_common import build_groq_client, call_groq
from vidbrief.config import Settings
from vidbrief.domain.errors import (
    AudioProcessingError,
    ExternalServiceError,
    NoSpeechDetectedError,
)
from vidbrief.domain.models import AudioChunk, Transcript, TranscriptSource
from vidbrief.domain.video import VideoId

logger = logging.getLogger(__name__)

# Whisper reads at most 224 prompt tokens, and its byte-level tokenizer never produces more
# tokens than UTF-8 bytes, so a byte cap stays within budget in every script.
_PROMPT_MAX_BYTES = 224
_LANGUAGE_RE = re.compile(r"[a-z]{2,3}")


class TranscriptionResult(Protocol):
    """The part of Groq's transcription response the adapter reads."""

    @property
    def text(self) -> str: ...


class TranscriptionEndpoint(Protocol):
    """The subset of ``groq.Groq().audio.transcriptions`` the adapter uses."""

    def create(
        self,
        *,
        model: str,
        file: tuple[str, bytes],
        language: str | Omit,
        prompt: str | Omit,
        response_format: Literal["json"],
        temperature: float,
    ) -> TranscriptionResult: ...


class GroqTranscriber:
    """Transcribe audio chunks one by one with a Groq Whisper model.

    Each chunk gets the retries of :func:`~vidbrief.adapters.groq_common.call_groq`.

    Args:
        endpoint: Groq's transcription endpoint, or a test double.
        model: The Whisper model name.
        sleep: Blocks between retries; replaceable in tests.
    """

    def __init__(
        self,
        *,
        endpoint: TranscriptionEndpoint,
        model: str,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build a transcriber that uses the configured key, timeout and model."""
        client = build_groq_client(settings)
        return cls(endpoint=client.audio.transcriptions, model=settings.transcription_model)

    @property
    def model(self) -> str:
        """The Whisper model name sent with every request."""
        return self._model

    def transcribe(
        self, video_id: VideoId, chunks: Sequence[AudioChunk], language: str | None
    ) -> Transcript:
        """Return the transcript of ``chunks``, joined in playback order.

        The end of the text transcribed so far is sent as Whisper's prompt so words and
        style carry over the cut between chunks.

        Raises:
            NoSpeechDetectedError: If nothing is said in the audio.
            RateLimitedError: If Groq's quota needs a wait longer than a minute.
            AudioProcessingError: If a chunk cannot be read.
            ExternalServiceError: If Groq fails, rejects the audio or answers unexpectedly.
        """
        whisper_language = _whisper_language(language)
        parts: list[str] = []
        for chunk in sorted(chunks, key=lambda chunk: chunk.index):
            text = self._transcribe_chunk(chunk, whisper_language, _prompt_tail(" ".join(parts)))
            if text:
                parts.append(text)

        if not parts:
            raise NoSpeechDetectedError("no_speech")
        return Transcript(
            video_id=video_id,
            language=whisper_language,
            source=TranscriptSource.SPEECH_TO_TEXT,
            text=" ".join(parts),
        )

    def _transcribe_chunk(self, chunk: AudioChunk, language: str | None, prompt: str) -> str:
        try:
            audio = chunk.path.read_bytes()
        except OSError as error:
            raise AudioProcessingError("chunk_unreadable") from error

        started = time.monotonic()
        response = call_groq(
            lambda: self._endpoint.create(
                model=self._model,
                file=(chunk.path.name, audio),
                language=language or omit,
                prompt=prompt or omit,
                response_format="json",
                temperature=0.0,
            ),
            service="transcription",
            sleep=self._sleep,
            log_extra={"chunk_index": chunk.index},
        )

        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise ExternalServiceError("transcription_bad_response")
        logger.info(
            "audio chunk transcribed",
            extra={
                "chunk_index": chunk.index,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            },
        )
        return text.strip()


def _whisper_language(language: str | None) -> str | None:
    if not language:
        return None
    base = language.split("-", 1)[0].lower()
    return base if _LANGUAGE_RE.fullmatch(base) else None


def _prompt_tail(text: str) -> str:
    encoded = text.encode()
    if len(encoded) <= _PROMPT_MAX_BYTES:
        return text
    tail = encoded[-_PROMPT_MAX_BYTES:].decode(errors="ignore")
    # The byte cut usually lands inside a word; a fragment would only mislead Whisper.
    _, space, rest = tail.partition(" ")
    return rest if space and rest else tail
