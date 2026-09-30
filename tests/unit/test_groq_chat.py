"""Tests for the Groq chat client wrapper, run against the real SDK over a mock transport."""

import json
from collections.abc import Callable

import groq
import httpx
import pytest

from vidbrief.adapters.groq_chat import ChatCompleter, GroqChatCompleter

MODEL = "chat-test-model"
SCHEMA: dict[str, object] = {"type": "object", "properties": {}, "additionalProperties": False}


def _completion(
    content: str | None = "hello", finish_reason: str = "stop", *, choices: bool = True
) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ]
        if choices
        else [],
    }


class Server:
    """Answers every request with one scripted response and keeps the request bodies."""

    def __init__(
        self,
        body: dict[str, object] | None = None,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = _completion() if body is None else body
        self._status_code = status_code
        self._headers = headers or {}
        self.requests: list[dict[str, object]] = []

    def handler(self) -> Callable[[httpx.Request], httpx.Response]:
        def _handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(json.loads(request.content))
            return httpx.Response(self._status_code, json=self._body, headers=self._headers)

        return _handle

    def completer(self) -> GroqChatCompleter:
        client = groq.Groq(
            api_key="test-key",  # pragma: allowlist secret
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler())),
        )
        return GroqChatCompleter(client=client, model=MODEL)


def test_satisfies_the_completer_protocol() -> None:
    completer: ChatCompleter = Server().completer()

    assert completer is not None


def test_sends_a_system_and_a_user_message_with_low_reasoning() -> None:
    server = Server()

    server.completer().complete(system="rules", user="data", max_completion_tokens=321)

    [body] = server.requests
    assert body["model"] == MODEL
    assert body["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "data"},
    ]
    assert body["max_completion_tokens"] == 321
    assert body["reasoning_effort"] == "low"
    assert body["include_reasoning"] is False
    assert "response_format" not in body


def test_requests_strict_json_when_a_schema_is_given() -> None:
    server = Server()

    server.completer().complete(
        system="rules", user="data", max_completion_tokens=10, json_schema=SCHEMA
    )

    assert server.requests[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "summary", "strict": True, "schema": SCHEMA},
    }


def test_returns_the_reply_and_the_token_limit_header() -> None:
    server = Server(headers={"x-ratelimit-limit-tokens": "250000"})

    reply = server.completer().complete(system="s", user="u", max_completion_tokens=10)

    assert reply.content == "hello"
    assert reply.truncated is False
    assert reply.tokens_per_minute == 250000


def test_flags_replies_cut_by_the_token_limit() -> None:
    server = Server(_completion("partial", "length"))

    reply = server.completer().complete(system="s", user="u", max_completion_tokens=10)

    assert reply.content == "partial"
    assert reply.truncated is True


@pytest.mark.parametrize("header", [None, "", "lots", "-5", "0"])
def test_ignores_a_missing_or_malformed_token_limit(header: str | None) -> None:
    server = Server(headers={} if header is None else {"x-ratelimit-limit-tokens": header})

    reply = server.completer().complete(system="s", user="u", max_completion_tokens=10)

    assert reply.tokens_per_minute is None


@pytest.mark.parametrize(
    "body", [_completion(None), _completion(choices=False)], ids=["null_content", "no_choices"]
)
def test_missing_content_becomes_an_empty_reply(body: dict[str, object]) -> None:
    reply = Server(body).completer().complete(system="s", user="u", max_completion_tokens=10)

    assert reply.content == ""


def test_http_errors_surface_as_groq_errors() -> None:
    server = Server({"error": {"message": "slow down"}}, status_code=429)

    with pytest.raises(groq.RateLimitError):
        server.completer().complete(system="s", user="u", max_completion_tokens=10)
