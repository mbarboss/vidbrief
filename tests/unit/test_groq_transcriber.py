"""Tests for the Groq Whisper transcriber."""

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import groq
import httpx
import pytest
from groq import Omit, omit

from vidbrief.adapters.groq_transcriber import GroqTranscriber, TranscriptionResult
from vidbrief.config import Settings
from vidbrief.domain.errors import (
    AudioProcessingError,
    ExternalServiceError,
    NoSpeechDetectedError,
    RateLimitedError,
)
from vidbrief.domain.models import AudioChunk, TranscriptSource
from vidbrief.domain.ports import Transcriber
from vidbrief.domain.video import VideoId

VIDEO_ID = VideoId("jNQXAC9IVRw")
MODEL = "whisper-test-model"
FAKE_API_KEY = "gsk_test_not_a_real_key"  # pragma: allowlist secret
_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")

Outcome = str | Exception | TranscriptionResult


class FakeEndpoint:
    """Replays scripted outcomes and records every request."""

    def __init__(self, *outcomes: Outcome) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(
        self,
        *,
        model: str,
        file: tuple[str, bytes],
        language: str | Omit,
        prompt: str | Omit,
        response_format: Literal["json"],
        temperature: float,
    ) -> TranscriptionResult:
        self.calls.append(
            {
                "model": model,
                "file": file,
                "language": language,
                "prompt": prompt,
                "response_format": response_format,
                "temperature": temperature,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, str):
            return cast(TranscriptionResult, SimpleNamespace(text=outcome))
        return outcome


def _status_error(
    error_type: type[groq.APIStatusError],
    status_code: int,
    headers: dict[str, str] | None = None,
) -> groq.APIStatusError:
    response = httpx.Response(status_code, headers=headers, request=_REQUEST)
    return error_type("provider message", response=response, body=None)


def _rate_limited(retry_after: str | None) -> groq.APIStatusError:
    headers = {} if retry_after is None else {"retry-after": retry_after}
    return _status_error(groq.RateLimitError, 429, headers)


def _chunks(tmp_path: Path, count: int = 1) -> list[AudioChunk]:
    chunks = []
    for index in range(count):
        path = tmp_path / f"{VIDEO_ID.value}.chunk{index:03d}.ogg"
        path.write_bytes(f"audio {index}".encode())
        chunks.append(AudioChunk(index=index, path=path))
    return chunks


class Harness:
    def __init__(self, *outcomes: Outcome) -> None:
        self.endpoint = FakeEndpoint(*outcomes)
        self.sleeps: list[float] = []
        self.transcriber = GroqTranscriber(
            endpoint=self.endpoint, model=MODEL, sleep=self.sleeps.append
        )


def test_satisfies_the_transcriber_port() -> None:
    transcriber: Transcriber = Harness().transcriber

    assert transcriber is not None


class TestSuccessfulTranscription:
    def test_returns_a_speech_to_text_transcript(self, tmp_path: Path) -> None:
        harness = Harness("  I'm at the zoo.  ")

        transcript = harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), "en")

        assert transcript.video_id == VIDEO_ID
        assert transcript.source is TranscriptSource.SPEECH_TO_TEXT
        assert transcript.text == "I'm at the zoo."
        assert transcript.language == "en"

    def test_sends_the_chunk_with_deterministic_settings(self, tmp_path: Path) -> None:
        harness = Harness("text")

        harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        [call] = harness.endpoint.calls
        assert call["model"] == MODEL
        assert call["file"] == (f"{VIDEO_ID.value}.chunk000.ogg", b"audio 0")
        assert call["response_format"] == "json"
        assert call["temperature"] == 0.0

    def test_transcribes_chunks_in_playback_order(self, tmp_path: Path) -> None:
        harness = Harness("first", "second", "third")
        chunks = _chunks(tmp_path, 3)

        transcript = harness.transcriber.transcribe(VIDEO_ID, list(reversed(chunks)), None)

        assert transcript.text == "first second third"
        assert [call["file"] for call in harness.endpoint.calls] == [
            (chunk.path.name, chunk.path.read_bytes()) for chunk in chunks
        ]

    def test_skips_chunks_without_speech(self, tmp_path: Path) -> None:
        harness = Harness("first", "   ", "third")

        transcript = harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path, 3), None)

        assert transcript.text == "first third"


class TestContinuityPrompt:
    def test_first_chunk_has_no_prompt(self, tmp_path: Path) -> None:
        harness = Harness("text")

        harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert harness.endpoint.calls[0]["prompt"] is omit

    def test_later_chunks_receive_the_previous_text(self, tmp_path: Path) -> None:
        harness = Harness("first part", "second part", "third")

        harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path, 3), None)

        prompts = [call["prompt"] for call in harness.endpoint.calls]
        assert prompts[1:] == ["first part", "first part second part"]

    def test_prompt_keeps_only_the_tail_starting_at_a_word(self, tmp_path: Path) -> None:
        long_text = " ".join(f"word{number}" for number in range(200))
        harness = Harness(long_text, "end")

        harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path, 2), None)

        prompt = harness.endpoint.calls[1]["prompt"]
        assert isinstance(prompt, str)
        assert 0 < len(prompt.encode()) <= 224
        assert long_text.endswith(prompt)
        assert prompt.startswith("word")
        assert long_text[len(long_text) - len(prompt) - 1] == " "

    def test_prompt_never_exceeds_the_token_budget_in_any_script(self, tmp_path: Path) -> None:
        long_text = "漢字" * 200
        harness = Harness(long_text, "end")

        harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path, 2), None)

        prompt = harness.endpoint.calls[1]["prompt"]
        assert isinstance(prompt, str)
        assert 0 < len(prompt.encode()) <= 224
        assert long_text.endswith(prompt)

    def test_no_prompt_while_nothing_was_said(self, tmp_path: Path) -> None:
        harness = Harness("", "text")

        harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path, 2), None)

        assert harness.endpoint.calls[1]["prompt"] is omit


class TestLanguageHint:
    @pytest.mark.parametrize(
        ("language", "expected"),
        [("en", "en"), ("pt-BR", "pt"), ("zh-Hans", "zh"), ("EN", "en"), ("haw", "haw")],
    )
    def test_sends_the_base_language_code(
        self, tmp_path: Path, language: str, expected: str
    ) -> None:
        harness = Harness("text")

        transcript = harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), language)

        assert harness.endpoint.calls[0]["language"] == expected
        assert transcript.language == expected

    @pytest.mark.parametrize("language", [None, "", "english", "12", "e", "../en"])
    def test_omits_missing_or_malformed_codes(self, tmp_path: Path, language: str | None) -> None:
        harness = Harness("text")

        transcript = harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), language)

        assert harness.endpoint.calls[0]["language"] is omit
        assert transcript.language is None


class TestNoSpeech:
    def test_rejects_audio_without_any_speech(self, tmp_path: Path) -> None:
        harness = Harness(" ", "")

        with pytest.raises(NoSpeechDetectedError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path, 2), None)

        assert caught.value.reason == "no_speech"

    def test_rejects_an_empty_chunk_list(self) -> None:
        harness = Harness()

        with pytest.raises(NoSpeechDetectedError):
            harness.transcriber.transcribe(VIDEO_ID, [], None)

        assert harness.endpoint.calls == []


class TestTransientFailures:
    @pytest.mark.parametrize(
        "error",
        [
            groq.APITimeoutError(_REQUEST),
            groq.APIConnectionError(request=_REQUEST),
            _status_error(groq.InternalServerError, 500),
            _status_error(groq.InternalServerError, 503),
        ],
        ids=["timeout", "connection", "500", "503"],
    )
    def test_retries_with_exponential_backoff(self, tmp_path: Path, error: Exception) -> None:
        harness = Harness(error, error, "recovered")

        transcript = harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert transcript.text == "recovered"
        assert harness.sleeps == [1.0, 2.0]

    def test_gives_up_after_three_attempts(self, tmp_path: Path) -> None:
        error = _status_error(groq.InternalServerError, 502)
        harness = Harness(error, error, error)

        with pytest.raises(ExternalServiceError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert caught.value.reason == "transcription_unavailable"
        assert len(harness.endpoint.calls) == 3

    def test_connection_failures_map_to_unavailable(self, tmp_path: Path) -> None:
        error = groq.APIConnectionError(request=_REQUEST)
        harness = Harness(error, error, error)

        with pytest.raises(ExternalServiceError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert caught.value.reason == "transcription_unavailable"

    def test_logs_retries_without_transcript_text(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="vidbrief")
        harness = Harness(
            "secret words", _status_error(groq.InternalServerError, 500), "more words"
        )

        harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path, 2), None)

        [retry] = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert getattr(retry, "chunk_index", None) == 1
        assert getattr(retry, "attempt", None) == 1
        assert getattr(retry, "error_type", None) == "InternalServerError"
        for record in caplog.records:
            rendered = f"{record.getMessage()} {record.__dict__}"
            assert "secret words" not in rendered
            assert "more words" not in rendered


class TestRateLimits:
    def test_waits_as_long_as_the_service_asks(self, tmp_path: Path) -> None:
        harness = Harness(_rate_limited("7"), "text")

        transcript = harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert transcript.text == "text"
        assert harness.sleeps == [7.0]

    @pytest.mark.parametrize(
        "retry_after", ["3600", "61", None, "soon", "-1", "Wed, 21 Oct 2026 07:28:00 GMT"]
    )
    def test_fails_fast_when_the_wait_is_long_or_unknown(
        self, tmp_path: Path, retry_after: str | None
    ) -> None:
        harness = Harness(_rate_limited(retry_after))

        with pytest.raises(RateLimitedError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert caught.value.reason == "transcription_rate_limited"
        assert len(harness.endpoint.calls) == 1
        assert harness.sleeps == []

    def test_gives_up_when_limits_persist(self, tmp_path: Path) -> None:
        harness = Harness(_rate_limited("1"), _rate_limited("1"), _rate_limited("1"))

        with pytest.raises(RateLimitedError):
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert len(harness.endpoint.calls) == 3


class TestPermanentFailures:
    @pytest.mark.parametrize(
        ("error_type", "status_code"),
        [(groq.AuthenticationError, 401), (groq.PermissionDeniedError, 403)],
    )
    def test_credential_problems_are_not_retried(
        self, tmp_path: Path, error_type: type[groq.APIStatusError], status_code: int
    ) -> None:
        harness = Harness(_status_error(error_type, status_code))

        with pytest.raises(ExternalServiceError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert caught.value.reason == "transcription_auth_failed"
        assert len(harness.endpoint.calls) == 1

    @pytest.mark.parametrize(
        ("error_type", "status_code"),
        [
            (groq.BadRequestError, 400),
            (groq.UnprocessableEntityError, 422),
        ],
    )
    def test_rejected_requests_are_not_retried(
        self, tmp_path: Path, error_type: type[groq.APIStatusError], status_code: int
    ) -> None:
        harness = Harness(_status_error(error_type, status_code))

        with pytest.raises(ExternalServiceError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert caught.value.reason == "transcription_rejected"
        assert len(harness.endpoint.calls) == 1

    def test_oversized_audio_is_reported_as_too_large(self, tmp_path: Path) -> None:
        harness = Harness(_status_error(groq.APIStatusError, 413))

        with pytest.raises(ExternalServiceError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert caught.value.reason == "transcription_request_too_large"
        assert len(harness.endpoint.calls) == 1

    def test_error_never_echoes_the_provider_message(self, tmp_path: Path) -> None:
        harness = Harness(_status_error(groq.BadRequestError, 400))

        with pytest.raises(ExternalServiceError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert "provider message" not in str(caught.value)
        assert "provider message" not in caught.value.user_message

    @pytest.mark.parametrize(
        "outcome",
        [
            cast(TranscriptionResult, SimpleNamespace(text=None)),
            groq.APIResponseValidationError(
                response=httpx.Response(200, request=_REQUEST), body=None
            ),
        ],
        ids=["missing_text", "invalid_response"],
    )
    def test_unexpected_responses_are_reported(
        self, tmp_path: Path, outcome: TranscriptionResult | Exception
    ) -> None:
        harness = Harness(outcome)

        with pytest.raises(ExternalServiceError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, _chunks(tmp_path), None)

        assert caught.value.reason == "transcription_bad_response"

    def test_unreadable_chunk_is_an_audio_error(self, tmp_path: Path) -> None:
        harness = Harness("text")
        missing = AudioChunk(index=0, path=tmp_path / "missing.ogg")

        with pytest.raises(AudioProcessingError) as caught:
            harness.transcriber.transcribe(VIDEO_ID, [missing], None)

        assert caught.value.reason == "chunk_unreadable"
        assert harness.endpoint.calls == []


class TestFromSettings:
    def test_uses_the_configured_model(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A developer's real .env or exported variables must never leak into test results.
        monkeypatch.chdir(tmp_path)
        for name in list(os.environ):
            if name == "GROQ_API_KEY" or name.startswith("VIDBRIEF_"):
                monkeypatch.delenv(name)
        monkeypatch.setenv("GROQ_API_KEY", FAKE_API_KEY)
        monkeypatch.setenv("VIDBRIEF_TRANSCRIPTION_MODEL", MODEL)

        transcriber = GroqTranscriber.from_settings(Settings())

        assert transcriber.model == MODEL
