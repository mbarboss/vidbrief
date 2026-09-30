"""Tests for the Groq client factory and the shared retry and error translation."""

import logging
import os
from pathlib import Path

import groq
import httpx
import pytest

from vidbrief.adapters.groq_common import build_groq_client, call_groq
from vidbrief.config import Settings
from vidbrief.domain.errors import ExternalServiceError, RateLimitedError

FAKE_API_KEY = "gsk_test_not_a_real_key"  # pragma: allowlist secret
_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _status_error(status_code: int, headers: dict[str, str] | None = None) -> groq.APIStatusError:
    response = httpx.Response(status_code, headers=headers, request=_REQUEST)
    error_type = {429: groq.RateLimitError, 500: groq.InternalServerError}.get(
        status_code, groq.APIStatusError
    )
    return error_type("provider message", response=response, body=None)


class Script:
    def __init__(self, *outcomes: str | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TestCallGroq:
    def test_returns_the_result_and_retries_transient_failures(self) -> None:
        script = Script(_status_error(500), "done")
        sleeps: list[float] = []

        result = call_groq(script, service="summary", sleep=sleeps.append, log_extra={})

        assert result == "done"
        assert sleeps == [1.0]

    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (_status_error(400), "summary_rejected"),
            (_status_error(413), "summary_request_too_large"),
            (_status_error(401), "summary_rejected"),
            (
                groq.AuthenticationError(
                    "m", response=httpx.Response(401, request=_REQUEST), body=None
                ),
                "summary_auth_failed",
            ),
        ],
    )
    def test_reason_codes_carry_the_service_name(self, error: Exception, reason: str) -> None:
        with pytest.raises(ExternalServiceError) as caught:
            call_groq(Script(error), service="summary", sleep=lambda _: None, log_extra={})

        assert caught.value.reason == reason

    def test_long_rate_limits_raise_the_generic_quota_error(self) -> None:
        error = _status_error(429, {"retry-after": "3600"})

        with pytest.raises(RateLimitedError) as caught:
            call_groq(Script(error), service="summary", sleep=lambda _: None, log_extra={})

        assert caught.value.reason == "summary_rate_limited"

    def test_retry_logs_name_the_service_and_context(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="vidbrief")

        call_groq(
            Script(_status_error(500), "done"),
            service="summary",
            sleep=lambda _: None,
            log_extra={"phase": "map"},
        )

        [record] = caplog.records
        assert getattr(record, "service", None) == "summary"
        assert getattr(record, "phase", None) == "map"
        assert getattr(record, "attempt", None) == 1


class TestBuildGroqClient:
    def test_builds_a_client_without_its_own_retries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A developer's real .env or exported variables must never leak into test results.
        monkeypatch.chdir(tmp_path)
        for name in list(os.environ):
            if name == "GROQ_API_KEY" or name.startswith("VIDBRIEF_"):
                monkeypatch.delenv(name)
        monkeypatch.setenv("GROQ_API_KEY", FAKE_API_KEY)
        monkeypatch.setenv("VIDBRIEF_REQUEST_TIMEOUT_SECONDS", "42")

        client = build_groq_client(Settings())

        assert client.api_key == FAKE_API_KEY
        assert client.max_retries == 0
        assert client.timeout == 42.0
