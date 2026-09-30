"""Speech-to-text backed by Groq's hosted Whisper models."""

import logging
import math
import re
import time
from collections.abc import Callable, Sequence
from typing import Literal, Protocol, Self

import groq
from groq import Omit, omit
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt

from vidbrief.config import Settings
from vidbrief.domain.errors import (
    AudioProcessingError,
    ExternalServiceError,
    NoSpeechDetectedError,
    TranscriptionRateLimitedError,
)
from vidbrief.domain.models import AudioChunk, Transcript, TranscriptSource
from vidbrief.domain.video import VideoId

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 8.0
# The free tier's hourly audio quota can ask for waits close to an hour; blocking a job
# that long is worse than telling the user to come back later.
_MAX_RETRY_AFTER_SECONDS = 60.0
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


def build_groq_client(settings: Settings) -> groq.Groq:
    """Create a Groq client from ``settings`` with the SDK's own retries disabled.

    Retries are handled by the adapters, which know which waits are worth making.
    """
    return groq.Groq(
        api_key=settings.groq_api_key.get_secret_value(),
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


class GroqTranscriber:
    """Transcribe audio chunks one by one with a Groq Whisper model.

    Timeouts, connection failures, 5xx responses and short rate-limit waits are retried
    up to three attempts per chunk; every other failure is reported at once.

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
            TranscriptionRateLimitedError: If Groq's quota needs a wait longer than a minute.
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

        retrying = Retrying(
            stop=stop_after_attempt(_MAX_ATTEMPTS),
            retry=retry_if_exception(_is_transient),
            wait=_retry_wait_seconds,
            sleep=self._sleep,
            before_sleep=lambda state: _log_retry(chunk.index, state),
            reraise=True,
        )
        started = time.monotonic()
        try:
            for attempt in retrying:
                with attempt:
                    response = self._endpoint.create(
                        model=self._model,
                        file=(chunk.path.name, audio),
                        language=language or omit,
                        prompt=prompt or omit,
                        response_format="json",
                        temperature=0.0,
                    )
        except groq.GroqError as error:
            raise _translate_error(error) from error

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


def _retry_after_seconds(error: groq.RateLimitError) -> float | None:
    raw = error.response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _is_transient(error: BaseException) -> bool:
    if isinstance(error, groq.RateLimitError):
        wait = _retry_after_seconds(error)
        return wait is not None and wait <= _MAX_RETRY_AFTER_SECONDS
    if isinstance(error, groq.APIStatusError):
        return error.status_code >= 500
    return isinstance(error, groq.APIConnectionError)


def _retry_wait_seconds(state: RetryCallState) -> float:
    error = state.outcome.exception() if state.outcome else None
    if isinstance(error, groq.RateLimitError):
        return _retry_after_seconds(error) or 0.0
    return min(2.0 ** (state.attempt_number - 1), _MAX_BACKOFF_SECONDS)


def _log_retry(chunk_index: int, state: RetryCallState) -> None:
    error = state.outcome.exception() if state.outcome else None
    logger.warning(
        "transcription attempt failed, retrying",
        extra={
            "chunk_index": chunk_index,
            "attempt": state.attempt_number,
            "error_type": type(error).__name__,
            "wait_seconds": state.upcoming_sleep,
        },
    )


def _translate_error(error: groq.GroqError) -> ExternalServiceError:
    # Provider messages may quote the request, so only fixed reason codes leave the adapter.
    if isinstance(error, groq.RateLimitError):
        return TranscriptionRateLimitedError("transcription_rate_limited")
    if isinstance(error, groq.AuthenticationError | groq.PermissionDeniedError):
        return ExternalServiceError("transcription_auth_failed")
    if isinstance(error, groq.APIStatusError):
        reason = (
            "transcription_unavailable" if error.status_code >= 500 else "transcription_rejected"
        )
        return ExternalServiceError(reason)
    if isinstance(error, groq.APIConnectionError):
        return ExternalServiceError("transcription_unavailable")
    return ExternalServiceError("transcription_bad_response")
