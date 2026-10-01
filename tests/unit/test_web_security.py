"""Tests for the HTTP security middleware."""

import asyncio
import logging

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from vidbrief.web.security import (
    CONTENT_SECURITY_POLICY,
    CrossOriginGuardMiddleware,
    SecurityHeadersMiddleware,
)

BASE_URL = "http://127.0.0.1:8000"


async def _ok(request: Request) -> Response:
    return PlainTextResponse("ok")


async def _cached(request: Request) -> Response:
    return PlainTextResponse("ok", headers={"Cache-Control": "max-age=60"})


def _client(
    *middleware: type[SecurityHeadersMiddleware | CrossOriginGuardMiddleware],
) -> TestClient:
    app = Starlette(
        routes=[
            Route("/", _ok, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]),
            Route("/cached", _cached),
        ]
    )
    for cls in middleware:
        app.add_middleware(cls)
    return TestClient(app, base_url=BASE_URL)


class TestSecurityHeaders:
    def test_adds_the_strict_headers_to_every_response(self) -> None:
        response = _client(SecurityHeadersMiddleware).get("/")

        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"
        assert response.headers["x-frame-options"] == "DENY"
        assert "camera=()" in response.headers["permissions-policy"]
        assert response.headers["cache-control"] == "no-store"

    def test_also_covers_error_responses(self) -> None:
        response = _client(SecurityHeadersMiddleware).get("/missing")

        assert response.status_code == 404
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY

    def test_keeps_a_cache_policy_set_by_the_route(self) -> None:
        response = _client(SecurityHeadersMiddleware).get("/cached")

        assert response.headers["cache-control"] == "max-age=60"

    @pytest.mark.parametrize(
        "directive",
        [
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' https://i.ytimg.com",
            "connect-src 'self'",
            "font-src 'self'",
            "form-action 'self'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ],
    )
    def test_policy_allows_only_local_resources_and_youtube_thumbnails(
        self, directive: str
    ) -> None:
        assert directive in CONTENT_SECURITY_POLICY.split("; ")

    def test_policy_never_allows_inline_code_or_eval(self) -> None:
        assert "unsafe" not in CONTENT_SECURITY_POLICY


class TestCrossOriginGuard:
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_safe_methods_always_pass(self, method: str) -> None:
        response = _client(CrossOriginGuardMiddleware).request(
            method, "/", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("site", ["same-origin", "none"])
    def test_same_origin_or_user_initiated_requests_pass(self, site: str) -> None:
        response = _client(CrossOriginGuardMiddleware).post("/", headers={"Sec-Fetch-Site": site})

        assert response.status_code == 200

    @pytest.mark.parametrize("site", ["cross-site", "same-site", "bogus"])
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_other_sites_cannot_change_state(self, site: str, method: str) -> None:
        response = _client(CrossOriginGuardMiddleware).request(
            method, "/", headers={"Sec-Fetch-Site": site}
        )

        assert response.status_code == 403
        assert response.text == "Cross-origin request blocked."

    def test_fetch_metadata_wins_over_a_matching_origin(self) -> None:
        response = _client(CrossOriginGuardMiddleware).post(
            "/", headers={"Sec-Fetch-Site": "cross-site", "Origin": BASE_URL}
        )

        assert response.status_code == 403

    def test_without_fetch_metadata_a_matching_origin_passes(self) -> None:
        response = _client(CrossOriginGuardMiddleware).post("/", headers={"Origin": BASE_URL})

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.example",
            "http://127.0.0.1:9999",
            "https://127.0.0.1:8000",
            "http://localhost:8000",
            "null",
        ],
    )
    def test_without_fetch_metadata_another_origin_is_blocked(self, origin: str) -> None:
        response = _client(CrossOriginGuardMiddleware).post("/", headers={"Origin": origin})

        assert response.status_code == 403

    def test_requests_without_browser_headers_pass(self) -> None:
        # Only browsers can be tricked into sending cross-site requests, and every browser
        # the app supports sends at least one of the two headers on unsafe requests.
        response = _client(CrossOriginGuardMiddleware).post("/")

        assert response.status_code == 200

    def test_blocked_requests_are_logged_without_the_origin(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="vidbrief.web.security"):
            _client(CrossOriginGuardMiddleware).post(
                "/", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}
            )

        [record] = caplog.records
        assert record.reason == "cross_origin_request"  # type: ignore[attr-defined]
        assert "evil.example" not in caplog.text


@pytest.mark.parametrize("middleware", [SecurityHeadersMiddleware, CrossOriginGuardMiddleware])
def test_non_http_events_pass_through_untouched(
    middleware: type[SecurityHeadersMiddleware | CrossOriginGuardMiddleware],
) -> None:
    seen: list[Scope] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope)

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        raise AssertionError("nothing is sent")

    scope: Scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
    asyncio.run(middleware(inner)(scope, receive, send))

    assert seen == [scope]
