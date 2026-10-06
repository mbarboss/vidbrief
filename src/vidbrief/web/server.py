"""Run the web app with uvicorn."""

import ipaddress
from collections.abc import Callable
from typing import Protocol

import uvicorn
from starlette.types import ASGIApp

from vidbrief.config import ALL_INTERFACES


class Server(Protocol):
    def __call__(self, app: ASGIApp, *, host: str, port: int) -> None: ...


def run_server(
    app: ASGIApp, *, host: str, port: int, run: Callable[..., None] = uvicorn.run
) -> None:
    """Serve ``app`` until interrupted.

    Logging is left to the app's JSON setup, the access log is off because URLs may carry
    user input, and forwarded headers are ignored since no proxy sits in front.
    """
    run(
        app,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        server_header=False,
        proxy_headers=False,
    )


def server_url(host: str, port: int) -> str:
    """The address users open in their browser.

    A server listening on all interfaces (container mode) is reached through ``localhost``.
    """
    return f"http://{'localhost' if host == ALL_INTERFACES else url_host(host)}:{port}"


def url_host(host: str) -> str:
    """``host`` as written in URLs and Host headers, where IPv6 addresses need brackets."""
    try:
        is_ipv6 = ipaddress.ip_address(host).version == 6
    except ValueError:
        is_ipv6 = False
    return f"[{host}]" if is_ipv6 else host
