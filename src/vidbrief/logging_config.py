"""Structured JSON logging with redaction of API keys and other configured secrets."""

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, TextIO

from vidbrief.config import LogLevel

_REDACTED = "[REDACTED]"
_GROQ_KEY_PATTERN = r"gsk_[A-Za-z0-9]{20,}"
_HANDLER_NAME = "vidbrief-json"
# Anything a LogRecord carries by default; every other attribute came from ``extra=``.
_STANDARD_RECORD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_TRACEBACK_FORMATTER = logging.Formatter()
# Extra values of these types cannot hold a secret and stay native JSON values.
_JSON_SCALARS = (bool, int, float, type(None))


class SecretRedactionFilter(logging.Filter):
    """Replace Groq API keys and the given secret values with ``[REDACTED]``.

    Covers the formatted message, ``extra`` fields (non-scalar values are rendered as text
    first), tracebacks and stack info. It is
    attached to the handler rather than a logger so records from every module are covered.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        # Blank values are dropped because an empty pattern would match between every
        # character; longer secrets go first so one that contains another is fully masked.
        literals = sorted({secret for secret in secrets if secret.strip()}, key=len, reverse=True)
        self._pattern = re.compile("|".join([_GROQ_KEY_PATTERN, *map(re.escape, literals)]))

    def redact(self, text: str) -> str:
        """Return ``text`` with every known secret masked."""
        return self._pattern.sub(_REDACTED, text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            # Mismatched format args would otherwise raise inside the caller's log statement;
            # the args are discarded because they are exactly where a secret could hide.
            message = str(record.msg)
        record.msg, record.args = self.redact(message), None

        if record.exc_info and not record.exc_text:
            record.exc_text = _TRACEBACK_FORMATTER.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)

        for key, value in list(vars(record).items()):
            if key in _STANDARD_RECORD_ATTRS or isinstance(value, _JSON_SCALARS):
                continue
            # Containers and objects are rendered as text first so a secret nested inside a
            # dict or an exception is masked too.
            setattr(record, key, self.redact(value if isinstance(value, str) else str(value)))
        return True


class JsonFormatter(logging.Formatter):
    """Render each record as a single-line JSON object, including ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value for key, value in vars(record).items() if key not in _STANDARD_RECORD_ATTRS
        }
        payload: dict[str, Any] = {
            **extras,
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            payload["exception"] = record.exc_text
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: LogLevel,
    *,
    secrets: Iterable[str] = (),
    stream: TextIO | None = None,
) -> None:
    """Route all logging to one JSON handler on the root logger.

    Safe to call more than once: the handler installed by a previous call is replaced, so
    records are never emitted twice.

    Args:
        level: Minimum level emitted by the root logger.
        secrets: Literal values to mask in addition to Groq-shaped API keys.
        stream: Destination for log lines; defaults to ``sys.stderr``.
    """
    handler = logging.StreamHandler(stream)
    handler.set_name(_HANDLER_NAME)
    handler.addFilter(SecretRedactionFilter(secrets))
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for previous in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(previous)
        previous.close()
    root.addHandler(handler)
    root.setLevel(level)
