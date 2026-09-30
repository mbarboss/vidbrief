"""Groq client construction, retries and error translation shared by the Groq adapters."""

import logging
import math
from collections.abc import Callable, Mapping

import groq
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt

from vidbrief.config import Settings
from vidbrief.domain.errors import ExternalServiceError, RateLimitedError

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 8.0
# The free tier's quotas can ask for waits of up to an hour or a day; blocking a job that
# long is worse than telling the user to come back later.
_MAX_RETRY_AFTER_SECONDS = 60.0
_PAYLOAD_TOO_LARGE = 413


def build_groq_client(settings: Settings) -> groq.Groq:
    """Create a Groq client from ``settings`` with the SDK's own retries disabled.

    Retries are handled by :func:`call_groq`, which knows which waits are worth making.
    """
    return groq.Groq(
        api_key=settings.groq_api_key.get_secret_value(),
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


def call_groq[T](
    request: Callable[[], T],
    *,
    service: str,
    sleep: Callable[[float], None],
    log_extra: Mapping[str, object],
) -> T:
    """Run ``request`` with retries and translate Groq failures into domain errors.

    Timeouts, connection failures, 5xx responses and rate limits whose ``retry-after`` is
    at most a minute are retried up to three attempts; everything else fails at once.

    Args:
        request: The Groq call to make.
        service: Prefix of the reason codes, e.g. ``"summary"`` gives ``"summary_rejected"``.
        sleep: Blocks between retries; replaceable in tests.
        log_extra: Context added to retry log records; it must never hold user content.

    Raises:
        RateLimitedError: If Groq's quota needs a wait longer than a minute.
        ExternalServiceError: If Groq fails, rejects the request or answers unexpectedly.
    """
    retrying = Retrying(
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        retry=retry_if_exception(_is_transient),
        wait=_retry_wait_seconds,
        sleep=sleep,
        before_sleep=lambda state: _log_retry(service, log_extra, state),
        reraise=True,
    )
    try:
        return retrying(request)
    except groq.GroqError as error:
        raise _translate_error(error, service) from error


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


def _log_retry(service: str, log_extra: Mapping[str, object], state: RetryCallState) -> None:
    error = state.outcome.exception() if state.outcome else None
    logger.warning(
        "groq request failed, retrying",
        extra={
            **log_extra,
            "service": service,
            "attempt": state.attempt_number,
            "error_type": type(error).__name__,
            "wait_seconds": state.upcoming_sleep,
        },
    )


def _translate_error(error: groq.GroqError, service: str) -> ExternalServiceError:
    # Provider messages may quote the request, so only fixed reason codes leave the adapter.
    if isinstance(error, groq.RateLimitError):
        return RateLimitedError(f"{service}_rate_limited")
    if isinstance(error, groq.AuthenticationError | groq.PermissionDeniedError):
        return ExternalServiceError(f"{service}_auth_failed")
    if isinstance(error, groq.APIStatusError):
        if error.status_code >= 500:
            return ExternalServiceError(f"{service}_unavailable")
        if error.status_code == _PAYLOAD_TOO_LARGE:
            return ExternalServiceError(f"{service}_request_too_large")
        return ExternalServiceError(f"{service}_rejected")
    if isinstance(error, groq.APIConnectionError):
        return ExternalServiceError(f"{service}_unavailable")
    return ExternalServiceError(f"{service}_bad_response")
