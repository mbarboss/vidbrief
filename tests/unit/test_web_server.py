"""Tests for the uvicorn launcher."""

from typing import Any

import pytest
from starlette.types import ASGIApp, Receive, Scope, Send

from vidbrief.web.server import run_server, server_url


async def _app(scope: Scope, receive: Receive, send: Send) -> None:
    raise AssertionError("not called")


def test_runs_uvicorn_on_the_given_address_with_hardened_options() -> None:
    calls: list[tuple[ASGIApp, dict[str, Any]]] = []

    def fake_run(app: ASGIApp, **options: Any) -> None:
        calls.append((app, options))

    run_server(_app, host="127.0.0.1", port=8123, run=fake_run)

    [(app, options)] = calls
    assert app is _app
    assert options == {
        "host": "127.0.0.1",
        "port": 8123,
        "log_config": None,
        "access_log": False,
        "server_header": False,
        "proxy_headers": False,
    }


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("127.0.0.1", 8000, "http://127.0.0.1:8000"),
        ("localhost", 9000, "http://localhost:9000"),
        ("::1", 8000, "http://[::1]:8000"),
        ("0.0.0.0", 8000, "http://localhost:8000"),
    ],
)
def test_server_url_is_what_a_browser_opens(host: str, port: int, expected: str) -> None:
    assert server_url(host, port) == expected
