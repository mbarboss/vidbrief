"""Tests for structured JSON logging and secret redaction."""

import io
import json
import logging
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from vidbrief.logging_config import JsonFormatter, SecretRedactionFilter, configure_logging

FAKE_GROQ_KEY = "gsk_" + "x" * 48  # pragma: allowlist secret
CONFIGURED_SECRET = "not-a-groq-shaped-secret"  # pragma: allowlist secret
REDACTED = "[REDACTED]"

logger = logging.getLogger("vidbrief.test")


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def stream() -> io.StringIO:
    buffer = io.StringIO()
    configure_logging("DEBUG", secrets=[CONFIGURED_SECRET], stream=buffer)
    return buffer


def _records(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines()]


class TestJsonFormat:
    def test_emits_one_json_object_per_record(self, stream: io.StringIO) -> None:
        logger.info("hello %s", "world")

        [record] = _records(stream)
        assert record["message"] == "hello world"
        assert record["level"] == "INFO"
        assert record["logger"] == "vidbrief.test"
        assert datetime.fromisoformat(record["timestamp"]).tzinfo is not None

    def test_includes_extra_fields(self, stream: io.StringIO) -> None:
        logger.warning("url rejected", extra={"reason": "host_not_allowed"})

        [record] = _records(stream)
        assert record["reason"] == "host_not_allowed"

    def test_serializes_non_json_extras_as_strings(self, stream: io.StringIO) -> None:
        path = Path("audio/chunk.mp3")
        logger.info("saved", extra={"path": path})

        [record] = _records(stream)
        assert record["path"] == str(path)

    def test_drops_the_terminal_colored_copy_uvicorn_attaches(self, stream: io.StringIO) -> None:
        logger.info(
            "Started server process [%d]",
            42,
            extra={"color_message": "Started server process [\x1b[36m%d\x1b[0m]"},
        )

        [record] = _records(stream)
        assert "color_message" not in record
        assert record["message"] == "Started server process [42]"

    def test_keeps_numbers_and_booleans_as_json_values(self, stream: io.StringIO) -> None:
        logger.info("done", extra={"attempt": 2, "elapsed_seconds": 1.5, "truncated": False})

        [record] = _records(stream)
        assert record["attempt"] == 2
        assert record["elapsed_seconds"] == 1.5
        assert record["truncated"] is False

    def test_includes_exception_traceback(self, stream: io.StringIO) -> None:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.exception("call failed")

        [record] = _records(stream)
        assert "RuntimeError: boom" in record["exception"]

    def test_respects_configured_level(self) -> None:
        buffer = io.StringIO()
        configure_logging("WARNING", stream=buffer)

        logger.info("hidden")
        logger.warning("shown")

        assert [record["message"] for record in _records(buffer)] == ["shown"]

    def test_reconfiguring_replaces_the_previous_handler(self) -> None:
        first, second = io.StringIO(), io.StringIO()
        configure_logging("INFO", stream=first)
        configure_logging("INFO", stream=second)

        logger.info("once")

        assert first.getvalue() == ""
        assert len(_records(second)) == 1


@pytest.mark.parametrize("secret", [FAKE_GROQ_KEY, CONFIGURED_SECRET])
class TestSecretRedaction:
    def test_redacts_message(self, stream: io.StringIO, secret: str) -> None:
        logger.info(f"key={secret}")

        assert secret not in stream.getvalue()
        assert _records(stream)[0]["message"] == f"key={REDACTED}"

    def test_redacts_format_args(self, stream: io.StringIO, secret: str) -> None:
        logger.info("key=%s", secret)

        assert secret not in stream.getvalue()
        assert _records(stream)[0]["message"] == f"key={REDACTED}"

    def test_redacts_extra_fields(self, stream: io.StringIO, secret: str) -> None:
        logger.info("event", extra={"detail": f"key={secret}"})

        assert secret not in stream.getvalue()
        assert _records(stream)[0]["detail"] == f"key={REDACTED}"

    def test_redacts_extra_fields_that_are_not_strings(
        self, stream: io.StringIO, secret: str
    ) -> None:
        logger.warning(
            "request failed",
            extra={"payload": {"headers": {"authorization": secret}}, "error": ValueError(secret)},
        )

        output = stream.getvalue()
        assert secret not in output
        assert output.count("[REDACTED]") == 2

    def test_redacts_exception_traceback(self, stream: io.StringIO, secret: str) -> None:
        try:
            raise RuntimeError(f"auth failed for {secret}")
        except RuntimeError:
            logger.exception("call failed")

        assert secret not in stream.getvalue()
        assert REDACTED in _records(stream)[0]["exception"]


def test_includes_stack_info(stream: io.StringIO) -> None:
    logger.info("checkpoint %s", "reached", stack_info=True)

    [record] = _records(stream)
    assert "test_includes_stack_info" in record["stack"]


def _record_with_exception(message: str) -> logging.LogRecord:
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})


def test_filter_formats_and_redacts_unformatted_traceback() -> None:
    record = _record_with_exception(f"auth failed for {FAKE_GROQ_KEY}")

    SecretRedactionFilter().filter(record)

    assert record.exc_text is not None
    assert "RuntimeError" in record.exc_text
    assert FAKE_GROQ_KEY not in record.exc_text


def test_formatter_renders_traceback_without_the_filter() -> None:
    record = _record_with_exception("boom")

    payload = json.loads(JsonFormatter().format(record))

    assert "RuntimeError: boom" in payload["exception"]


def test_malformed_format_args_do_not_break_the_caller(stream: io.StringIO) -> None:
    logger.info("key=%s %s", FAKE_GROQ_KEY)

    assert FAKE_GROQ_KEY not in stream.getvalue()
    assert _records(stream)[0]["message"] == "key=%s %s"


def test_blank_secrets_are_ignored() -> None:
    buffer = io.StringIO()
    configure_logging("INFO", secrets=["", "   "], stream=buffer)

    logger.info("hello")

    assert _records(buffer)[0]["message"] == "hello"
