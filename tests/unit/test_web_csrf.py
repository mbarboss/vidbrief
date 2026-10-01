"""Tests for the CSRF token protection."""

import logging
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from vidbrief.web.csrf import (
    CSRF_COOKIE,
    CSRF_FIELD,
    CSRF_HEADER,
    CsrfProtector,
    require_csrf,
)

BASE_URL = "http://127.0.0.1:8000"


def _app(protector: CsrfProtector) -> FastAPI:
    app = FastAPI()
    app.state.csrf = protector

    @app.get("/form")
    def form(request: Request) -> Response:
        token = protector.token_for(request)
        response = JSONResponse({"token": token.value})
        protector.set_cookie(response, token)
        return response

    @app.post("/submit", dependencies=[Depends(require_csrf)])
    def submit(url: Annotated[str, Form()] = "") -> dict[str, str]:
        return {"url": url}

    @app.post("/ajax", dependencies=[Depends(require_csrf)])
    def ajax() -> dict[str, str]:
        return {"ok": "yes"}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app(CsrfProtector()), base_url=BASE_URL)


def _token(client: TestClient) -> str:
    token: str = client.get("/form").json()["token"]
    return token


class TestTokenFor:
    def test_sets_a_strict_http_only_session_cookie(self, client: TestClient) -> None:
        response = client.get("/form")

        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{CSRF_COOKIE}=")
        attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
        assert {"httponly", "samesite=strict", "path=/"} <= attributes
        assert not any(a.startswith(("max-age", "expires", "domain")) for a in attributes)

    def test_the_cookie_holds_a_nonce_and_not_the_token(self, client: TestClient) -> None:
        token = _token(client)

        assert client.cookies[CSRF_COOKIE] != token

    def test_reuses_the_nonce_so_tokens_in_other_tabs_stay_valid(self, client: TestClient) -> None:
        first = _token(client)
        nonce = client.cookies[CSRF_COOKIE]

        second = _token(client)

        assert second == first
        assert client.cookies[CSRF_COOKIE] == nonce

    def test_replaces_a_malformed_cookie(self, client: TestClient) -> None:
        response = client.get("/form", headers={"Cookie": f"{CSRF_COOKIE}={'x' * 5000}"})

        nonce = response.headers["set-cookie"].split(";")[0].removeprefix(f"{CSRF_COOKIE}=")
        assert len(nonce) == 43
        assert nonce != "x" * 43

    def test_different_visitors_get_different_tokens(self) -> None:
        app = _app(CsrfProtector())

        first = _token(TestClient(app, base_url=BASE_URL))
        second = _token(TestClient(app, base_url=BASE_URL))

        assert first != second


class TestVerify:
    def test_accepts_the_token_from_the_form_field(self, client: TestClient) -> None:
        token = _token(client)

        response = client.post("/submit", data={CSRF_FIELD: token, "url": "abc"})

        assert response.status_code == 200
        assert response.json() == {"url": "abc"}

    def test_accepts_the_token_from_the_header(self, client: TestClient) -> None:
        token = _token(client)

        response = client.post("/ajax", headers={CSRF_HEADER: token})

        assert response.status_code == 200

    def test_rejects_a_request_without_a_token(self, client: TestClient) -> None:
        _token(client)

        response = client.post("/submit", data={"url": "abc"})

        assert response.status_code == 403
        assert response.json() == {"detail": "The form expired. Reload the page and try again."}

    def test_rejects_a_wrong_token(self, client: TestClient) -> None:
        token = _token(client)

        forged = token[:-1] + ("B" if token.endswith("A") else "A")

        response = client.post("/ajax", headers={CSRF_HEADER: forged})

        assert response.status_code == 403

    def test_rejects_a_token_without_its_cookie(self, client: TestClient) -> None:
        token = _token(client)
        client.cookies.clear()

        response = client.post("/ajax", headers={CSRF_HEADER: token})

        assert response.status_code == 403

    def test_rejects_a_token_issued_by_a_previous_server_run(self, client: TestClient) -> None:
        old_server = TestClient(_app(CsrfProtector()), base_url=BASE_URL)
        token = _token(old_server)
        client.cookies.set(CSRF_COOKIE, old_server.cookies[CSRF_COOKIE])

        response = client.post("/ajax", headers={CSRF_HEADER: token})

        assert response.status_code == 403

    def test_rejects_a_malformed_cookie_with_any_token(self, client: TestClient) -> None:
        client.cookies.set(CSRF_COOKIE, "short")

        response = client.post("/ajax", headers={CSRF_HEADER: "anything"})

        assert response.status_code == 403

    def test_rejections_are_logged_with_a_reason_code(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="vidbrief.web.csrf"):
            client.post("/ajax", headers={CSRF_HEADER: "forged-token-value"})

        [record] = caplog.records
        assert record.reason == "csrf_token_invalid"  # type: ignore[attr-defined]
        assert "forged-token-value" not in caplog.text
