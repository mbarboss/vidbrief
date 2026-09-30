"""Thin wrapper over Groq chat completions that also exposes the reported token limit."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import groq
from groq import omit
from groq.types.chat.completion_create_params import ResponseFormat

_RATE_LIMIT_HEADER = "x-ratelimit-limit-tokens"


@dataclass(frozen=True, slots=True)
class ChatReply:
    """What the summarizer needs from one chat completion.

    Attributes:
        content: The assistant's text, empty when the model returned none.
        truncated: Whether generation stopped at ``max_completion_tokens``.
        tokens_per_minute: The token rate limit Groq reported for this key and model.
    """

    content: str
    truncated: bool
    tokens_per_minute: int | None


class ChatCompleter(Protocol):
    """Sends one system + user exchange to a chat model."""

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_completion_tokens: int,
        json_schema: Mapping[str, object] | None = None,
    ) -> ChatReply:
        """Return the model's reply; a ``json_schema`` forces strictly matching JSON.

        Raises:
            groq.GroqError: For any failure; callers decide about retries.
        """
        ...


class GroqChatCompleter:
    """Chat completions against Groq with low reasoning effort and hidden reasoning.

    Args:
        client: A configured Groq client.
        model: The chat model name.
    """

    def __init__(self, *, client: groq.Groq, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        """The chat model name sent with every request."""
        return self._model

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_completion_tokens: int,
        json_schema: Mapping[str, object] | None = None,
    ) -> ChatReply:
        """Return the model's reply; a ``json_schema`` forces strictly matching JSON.

        Raises:
            groq.GroqError: For any failure; callers decide about retries.
        """
        raw = self._client.chat.completions.with_raw_response.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=max_completion_tokens,
            # Reasoning tokens count against the completion budget and the per-minute
            # quota, and summarizing gains little from long deliberation.
            reasoning_effort="low",
            include_reasoning=False,
            response_format=_response_format(json_schema) if json_schema else omit,
        )
        completion = raw.parse()
        choice = completion.choices[0] if completion.choices else None
        return ChatReply(
            content=(choice.message.content or "") if choice else "",
            truncated=choice is not None and choice.finish_reason == "length",
            tokens_per_minute=_parse_limit(raw.headers.get(_RATE_LIMIT_HEADER)),
        )


def _response_format(schema: Mapping[str, object]) -> ResponseFormat:
    return {
        "type": "json_schema",
        "json_schema": {"name": "summary", "strict": True, "schema": dict(schema)},
    }


def _parse_limit(raw: str | None) -> int | None:
    if raw is None or not raw.isdigit():
        return None
    return int(raw) or None
