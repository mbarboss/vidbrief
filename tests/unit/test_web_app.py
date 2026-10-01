"""Tests for the web application factory."""

import pytest
from fastapi.testclient import TestClient

from tests.unit.conftest import SettingsFactory
from vidbrief.config import Settings
from vidbrief.domain.progress import ProgressCallback
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import PipelineResult
from vidbrief.web.app import allowed_hosts, create_app
from vidbrief.web.csrf import CsrfProtector
from vidbrief.web.security import CONTENT_SECURITY_POLICY

BASE_URL = "http://127.0.0.1:8000"


class UnusedRunner:
    def run(
        self, video_id: VideoId, language: str, on_progress: ProgressCallback
    ) -> PipelineResult:
        raise AssertionError("the pipeline must not run")


@pytest.fixture
def settings(make_settings: SettingsFactory) -> Settings:
    return make_settings()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, UnusedRunner()), base_url=BASE_URL)


def test_health_check(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_responses_carry_the_security_headers(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_not_exposed(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "127.0.0.1", "localhost"])
def test_loopback_host_names_are_accepted(client: TestClient, host: str) -> None:
    assert client.get("/healthz", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host", ["evil.example", "127.0.0.1.nip.io", "localhost.evil.example", "192.168.0.10:8000"]
)
def test_other_host_names_are_rejected_to_stop_dns_rebinding(client: TestClient, host: str) -> None:
    response = client.get("/healthz", headers={"Host": host})

    assert response.status_code == 400
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_cross_site_requests_are_blocked(client: TestClient) -> None:
    response = client.post("/healthz", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403


def test_keeps_its_dependencies_on_the_state(settings: Settings) -> None:
    runner = UnusedRunner()
    csrf = CsrfProtector()

    app = create_app(settings, runner, csrf=csrf)

    assert app.state.settings is settings
    assert app.state.runner is runner
    assert app.state.csrf is csrf


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", ["127.0.0.1", "localhost"]),
        ("localhost", ["localhost", "127.0.0.1"]),
        ("127.0.0.2", ["127.0.0.2", "localhost", "127.0.0.1"]),
        ("::1", ["[::1]", "localhost", "127.0.0.1"]),
    ],
)
def test_allowed_hosts_follow_the_bind_address(
    make_settings: SettingsFactory, host: str, expected: list[str]
) -> None:
    assert allowed_hosts(make_settings(host=host)) == expected


def test_ipv6_bind_address_accepts_its_bracketed_host(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(host="::1"), UnusedRunner())

    response = TestClient(app, base_url="http://[::1]:8000").get("/healthz")

    assert response.status_code == 200
