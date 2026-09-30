"""Application settings loaded from environment variables and an optional ``.env`` file."""

import ipaddress
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_LOOPBACK_HOSTNAMES = frozenset({"localhost"})


class Settings(BaseSettings):
    """Validated, immutable runtime configuration.

    Variables use the ``VIDBRIEF_`` prefix, except the Groq key, which keeps the
    provider's conventional ``GROQ_API_KEY`` name.
    """

    model_config = SettingsConfigDict(
        env_prefix="VIDBRIEF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        # Validation errors echo raw inputs by default, which would leak secrets into logs.
        hide_input_in_errors=True,
    )

    groq_api_key: SecretStr = Field(validation_alias="GROQ_API_KEY")
    transcription_model: str = Field(default="whisper-large-v3-turbo", min_length=1)
    summary_model: str = Field(default="openai/gpt-oss-120b", min_length=1)
    default_summary_language: str = "pt-BR"
    max_video_duration_seconds: int = Field(default=7200, gt=0)
    # Groq's free tier rejects uploads above 25 MB; the margin absorbs container overhead.
    audio_chunk_max_mb: int = Field(default=24, gt=0, le=100)
    # Unset means the summarizer sizes its requests from the token limit Groq reports; a
    # value pins the budget (prompt plus completion tokens) for every summary request.
    summary_max_request_tokens: int | None = Field(default=None, ge=2000, le=131_072)
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=4)
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    log_level: LogLevel = "INFO"

    @property
    def audio_chunk_max_bytes(self) -> int:
        """The audio chunk limit in bytes."""
        # Decimal megabytes are the smaller reading of "MB", so the limit holds whichever
        # unit the provider actually enforces.
        return self.audio_chunk_max_mb * 1_000_000

    @field_validator("groq_api_key")
    @classmethod
    def _reject_blank_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("GROQ_API_KEY must not be blank")
        return value

    @field_validator("default_summary_language")
    @classmethod
    def _require_supported_language(cls, value: str) -> str:
        # The language is interpolated into the LLM prompt, so only allowlisted codes are
        # accepted to rule out prompt injection through configuration.
        if value not in SUPPORTED_SUMMARY_LANGUAGES:
            supported = ", ".join(sorted(SUPPORTED_SUMMARY_LANGUAGES))
            raise ValueError(
                f"unsupported summary language {value!r}; expected one of: {supported}"
            )
        return value

    @field_validator("host")
    @classmethod
    def _require_loopback_host(cls, value: str) -> str:
        # vidbrief is local-only: a routable interface would expose a pipeline billed to the
        # owner's Groq account to everyone on the network.
        if value in _LOOPBACK_HOSTNAMES:
            return value
        try:
            is_loopback = ipaddress.ip_address(value).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ValueError(f"host must be a loopback address, got {value!r}")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, validated once on first access."""
    return Settings()
