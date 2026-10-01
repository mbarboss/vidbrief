"""Tests for the home page and the summary form."""

import base64
import hashlib
import logging
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from tests.unit.conftest import SettingsFactory
from vidbrief.domain.progress import ProgressCallback
from vidbrief.domain.video import VideoId
from vidbrief.services.pipeline import PipelineResult
from vidbrief.web import routes
from vidbrief.web.app import create_app
from vidbrief.web.csrf import CSRF_FIELD

BASE_URL = "http://127.0.0.1:8000"
HTMX = {"HX-Request": "true"}
VALID_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
# Pinned so a changed vendored file fails loudly; update only after verifying a new release.
# pragma: allowlist nextline secret
HTMX_SHA384 = "sha384-2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg"
STATIC_DIR = Path(routes.__file__).parent / "static"


class UnusedRunner:
    def run(
        self, video_id: VideoId, language: str, on_progress: ProgressCallback
    ) -> PipelineResult:
        raise AssertionError("the pipeline must not run")


class Page(HTMLParser):
    """Collects what the tests inspect: tags with their attributes and inline code."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.inline_code: list[str] = []
        self._open: str | None = None
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == "style" or (tag == "script" and "src" not in attributes):
            self.inline_code.append(tag)
        self.inline_code.extend(
            f"{tag}[{name}]" for name in attributes if name == "style" or name.startswith("on")
        )

    def find(self, tag: str, **wanted: str) -> list[dict[str, str | None]]:
        return [
            attributes
            for name, attributes in self.tags
            if name == tag and all(attributes.get(key) == value for key, value in wanted.items())
        ]


@pytest.fixture
def client(make_settings: SettingsFactory) -> TestClient:
    return TestClient(create_app(make_settings(), UnusedRunner()), base_url=BASE_URL)


def _csrf_token(client: TestClient) -> str:
    [field] = Page(client.get("/").text).find("input", name=CSRF_FIELD)
    token = field["value"]
    assert token
    return token


def _submit(client: TestClient, url: str, language: str = "en", *, htmx: bool = True) -> Response:
    data = {CSRF_FIELD: _csrf_token(client), "url": url, "language": language}
    return client.post("/summaries", data=data, headers=HTMX if htmx else {})


class TestHomePage:
    def test_renders_the_form(self, client: TestClient) -> None:
        response = client.get("/")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        page = Page(response.text)
        [form] = page.find("form", id="summary-form")
        assert form["method"] == "post"
        assert form["action"] == "/summaries"
        assert form["hx-post"] == "/summaries"
        assert page.find("input", name="url", type="url")

    def test_offers_every_language_with_the_default_selected(
        self, make_settings: SettingsFactory
    ) -> None:
        client = TestClient(
            create_app(make_settings(default_summary_language="es"), UnusedRunner()),
            base_url=BASE_URL,
        )

        page = Page(client.get("/").text)

        radios = page.find("input", type="radio", name="language")
        assert [radio["value"] for radio in radios] == [
            "pt-BR", "en", "es", "fr", "de", "it", "ja", "zh-CN"
        ]  # fmt: skip
        assert [radio["value"] for radio in radios if "checked" in radio] == ["es"]

    def test_sets_the_csrf_cookie_with_the_page(self, client: TestClient) -> None:
        response = client.get("/")

        assert "vidbrief_csrf=" in response.headers["set-cookie"]

    def test_shows_the_configured_limits_and_address(self, make_settings: SettingsFactory) -> None:
        settings = make_settings(max_video_duration_seconds="5400", port="8123")
        client = TestClient(create_app(settings, UnusedRunner()), base_url=BASE_URL)

        html = client.get("/", headers={"Host": "127.0.0.1:8123"}).text

        assert "90 minutes" in html
        assert "Running on 127.0.0.1:8123" in html

    def test_has_no_inline_code_so_the_strict_csp_holds(self, client: TestClient) -> None:
        assert Page(client.get("/").text).inline_code == []

    def test_loads_the_vendored_htmx_with_its_pinned_hash(self, client: TestClient) -> None:
        page = Page(client.get("/").text)

        [script] = page.find("script", src="/static/vendor/htmx-2.0.11.min.js")
        assert script["integrity"] == HTMX_SHA384
        body = client.get("/static/vendor/htmx-2.0.11.min.js").content
        assert "sha384-" + base64.b64encode(hashlib.sha384(body).digest()).decode() == (HTMX_SHA384)

    def test_configures_htmx_without_eval_or_history_cache(self, client: TestClient) -> None:
        page = Page(client.get("/").text)

        [meta] = page.find("meta", name="htmx-config")
        config = meta["content"] or ""
        for setting in (
            '"allowEval":false',
            '"allowScriptTags":false',
            '"includeIndicatorStyles":false',
            '"selfRequestsOnly":true',
            '"historyCacheSize":0',
            '{"code":"422","swap":true}',
        ):
            assert setting in config

    def test_every_referenced_asset_is_served_with_its_type(self, client: TestClient) -> None:
        page = Page(client.get("/").text)
        paths = [
            value
            for _, attributes in page.tags
            for key, value in attributes.items()
            if key in {"src", "href"} and value and value.startswith("/static/")
        ]
        css = client.get("/static/css/app.css").text
        paths += re.findall(r"url\(\"?(/static/[^\")]+)", css)
        expected_types = {
            ".css": "text/css",
            ".js": "text/javascript",
            ".woff2": "font/woff2",
            ".svg": "image/svg+xml",
        }

        assert len(paths) >= 6
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
            content_type = response.headers["content-type"].split(";")[0]
            assert content_type == expected_types[Path(path).suffix], path

    def test_vendored_licenses_ship_with_the_assets(self) -> None:
        for name in (
            "vendor/htmx-LICENSE.txt",
            "fonts/bricolage-grotesque-OFL.txt",
            "fonts/jetbrains-mono-OFL.txt",
        ):
            assert (STATIC_DIR / name).is_file(), name


class TestSubmitWithHtmx:
    def test_a_valid_link_replaces_the_form(self, client: TestClient) -> None:
        response = _submit(client, VALID_URL, "ja")

        assert response.status_code == 200
        assert response.headers["hx-retarget"] == "#summary-form"
        assert response.headers["hx-reswap"] == "outerHTML"
        assert "<code>jNQXAC9IVRw</code>" in response.text
        assert "https://youtu.be/jNQXAC9IVRw --language ja" in response.text
        assert "VideoId" not in response.text
        assert "日本語" in response.text
        assert Page(response.text).inline_code == []

    def test_an_invalid_link_returns_only_the_error_message(self, client: TestClient) -> None:
        response = _submit(client, "https://evil.example/<script>alert(1)</script>")

        assert response.status_code == 422
        assert response.text.strip() == "Please enter a valid YouTube video link."
        assert "hx-retarget" not in response.headers

    def test_a_language_outside_the_allowlist_is_rejected(self, client: TestClient) -> None:
        response = _submit(client, VALID_URL, "klingon")

        assert response.status_code == 422
        assert response.text.strip() == "Please choose one of the supported summary languages."

    def test_missing_fields_are_treated_as_invalid_input(self, client: TestClient) -> None:
        token = _csrf_token(client)

        response = client.post("/summaries", data={CSRF_FIELD: token}, headers=HTMX)

        assert response.status_code == 422
        assert response.text.strip() == "Please enter a valid YouTube video link."

    def test_rejections_are_logged_by_reason_without_the_input(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="vidbrief.web.routes"):
            _submit(client, "https://evil.example/secret-path")

        assert [getattr(r, "reason", None) for r in caplog.records] == ["host_not_allowed"]
        assert "secret-path" not in caplog.text

    def test_requires_the_csrf_token(self, client: TestClient) -> None:
        client.get("/")

        response = client.post("/summaries", data={"url": VALID_URL}, headers=HTMX)

        assert response.status_code == 403
        # Shown in the form's error slot, e.g. after a server restart expired the token.
        assert response.text == "The form expired. Reload the page and try again."


def test_accepted_requests_log_the_plain_video_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="vidbrief.web.routes"):
        _submit(client, VALID_URL)

    assert [getattr(r, "video_id", None) for r in caplog.records] == ["jNQXAC9IVRw"]


class TestSubmitWithoutJavaScript:
    def test_a_valid_link_renders_the_full_page(self, client: TestClient) -> None:
        response = _submit(client, VALID_URL, htmx=False)

        assert response.status_code == 200
        assert "<html" in response.text
        assert "<code>jNQXAC9IVRw</code>" in response.text
        assert not Page(response.text).find("form", id="summary-form")

    def test_an_invalid_link_renders_the_form_with_the_error(self, client: TestClient) -> None:
        response = _submit(client, "not a link <b>bold</b>", htmx=False)

        assert response.status_code == 422
        assert "Please enter a valid YouTube video link." in response.text
        assert "<b>bold</b>" not in response.text
        assert "not a link" not in response.text
        assert Page(response.text).find("form", id="summary-form")


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (7200, "2 hours"),
        (3600, "1 hour"),
        (5400, "90 minutes"),
        (60, "1 minute"),
        (90, "1 minute"),
        (45, "45 seconds"),
        (1, "1 second"),
    ],
)
def test_describe_duration(seconds: int, expected: str) -> None:
    assert routes.describe_duration(seconds) == expected
