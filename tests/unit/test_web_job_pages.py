"""Tests for starting summary jobs and following them in the browser."""

import base64
import hashlib
import html
import logging
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from tests.unit.conftest import SettingsFactory
from tests.unit.job_fakes import (
    METADATA,
    RESULT,
    VIDEO_ID,
    HeldThreads,
    ScriptedRunner,
    run_inline,
)
from tests.unit.test_web_home import BASE_URL, HTMX, Page
from vidbrief.domain.errors import VideoTooLongError
from vidbrief.domain.models import Summary, TranscriptSource
from vidbrief.domain.progress import PipelineStage, Progress
from vidbrief.services.report import to_markdown
from vidbrief.web.app import create_app
from vidbrief.web.csrf import CSRF_FIELD
from vidbrief.web.jobs import Job, JobManager

VALID_URL = "https://youtu.be/jNQXAC9IVRw"
# pragma: allowlist nextline secret
SSE_SHA384 = "sha384-A986SAtodyH8eg8x8irJnYUk7i9inVQqYigD6qZ9evobksGNIXfeFvDwLSHcp31N"
HOSTILE = "<script>alert(1)</script>"
MARKDOWN_TEMPLATE_RE = re.compile(r'<template id="summary-markdown">(.*?)</template>', re.DOTALL)


class App:
    def __init__(
        self,
        make_settings: SettingsFactory,
        runner: ScriptedRunner | None = None,
        *,
        hold: bool = False,
    ) -> None:
        self.runner = runner or ScriptedRunner()
        self.threads = HeldThreads()
        self.jobs = JobManager(
            self.runner, max_concurrent=1, start_thread=self.threads if hold else run_inline
        )
        app = create_app(make_settings(), self.runner, jobs=self.jobs)
        self.client = TestClient(app, base_url=BASE_URL)

    def submit(self, url: str = VALID_URL, language: str = "ja", *, htmx: bool = True) -> Response:
        [field] = Page(self.client.get("/").text).find("input", name=CSRF_FIELD)
        data = {CSRF_FIELD: field["value"] or "", "url": url, "language": language}
        return self.client.post(
            "/summaries", data=data, headers=HTMX if htmx else {}, follow_redirects=False
        )

    def start(self) -> Job:
        job_id = self.jobs.submit(VIDEO_ID, "en")
        job = self.jobs.get(job_id)
        assert job is not None
        return job


class TestStartingAJob:
    def test_htmx_requests_are_sent_to_the_job_page(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings)

        response = app.submit()

        assert response.status_code == 200
        job_url = response.headers["hx-redirect"]
        assert job_url.startswith("/jobs/")
        assert app.jobs.get(job_url.removeprefix("/jobs/")) is not None
        assert app.runner.calls == [(VIDEO_ID, "ja")]

    def test_plain_form_posts_are_redirected_to_the_job_page(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings)

        response = app.submit(htmx=False)

        assert response.status_code == 303
        assert response.headers["location"].startswith("/jobs/")

    def test_a_busy_server_asks_to_wait(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings, hold=True)
        app.start()

        response = app.submit()

        assert response.status_code == 429
        assert response.text == "Another summary is still running. Try again when it finishes."

    def test_a_busy_server_answers_plain_form_posts_with_the_page(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings, hold=True)
        app.start()

        response = app.submit(htmx=False)

        assert response.status_code == 429
        assert "Another summary is still running." in response.text
        assert Page(response.text).find("form", id="summary-form")

    def test_invalid_input_never_starts_a_job(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings)

        response = app.submit("https://evil.example/")

        assert response.status_code == 422
        assert app.runner.calls == []


class TestJobPage:
    def test_a_running_job_streams_its_progress(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings, hold=True)
        job = app.start()
        job.on_progress(Progress(PipelineStage.CHECKING_VIDEO))

        response = app.client.get(f"/jobs/{job.job_id}")

        assert response.status_code == 200
        page = Page(response.text)
        [live] = page.find("div", id="job-live")
        assert live["hx-ext"] == "sse"
        assert live["sse-connect"] == f"/jobs/{job.job_id}/events"
        assert live["sse-swap"] == "progress"
        assert live["sse-close"] == "end"
        assert "Working on it" in response.text
        assert "Checking the video" in response.text
        assert page.inline_code == []

    def test_without_javascript_a_running_job_page_refreshes_itself(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings, hold=True)
        job = app.start()

        html = app.client.get(f"/jobs/{job.job_id}").text

        assert '<noscript><meta http-equiv="refresh" content="3"></noscript>' in html

    def test_shows_the_video_once_known_with_its_title_escaped(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings, hold=True)
        job = app.start()
        thumbnail = "https://i.ytimg.com/vi/jNQXAC9IVRw/hqdefault.jpg"
        job.on_progress(
            Progress(
                PipelineStage.CHECKING_VIDEO,
                video=replace(METADATA, title=HOSTILE, thumbnail_url=thumbnail),
            )
        )

        html = app.client.get(f"/jobs/{job.job_id}").text

        assert HOSTILE not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        [image] = Page(html).find("img", src=thumbnail)
        assert image["alt"] == ""
        assert "0:19" in html

    def test_a_finished_job_shows_the_summary_without_streaming(
        self, make_settings: SettingsFactory
    ) -> None:
        summary = Summary(VIDEO_ID, "en", f"Gist {HOSTILE}", ("First point", f"Second {HOSTILE}"))
        result = replace(
            RESULT,
            summary=summary,
            transcript_source=TranscriptSource.SPEECH_TO_TEXT,
        )
        app = App(make_settings, ScriptedRunner(outcome=result))
        job = app.start()

        response = app.client.get(f"/jobs/{job.job_id}")

        page = Page(response.text)
        assert not page.find("div", **{"sse-connect": f"/jobs/{job.job_id}/events"})
        assert "<noscript><meta" not in response.text
        assert HOSTILE not in response.text
        assert "Gist &lt;script&gt;" in response.text
        assert "First point" in response.text
        assert "From the audio" in response.text
        assert "Done in" in response.text
        assert "English" in response.text

    def test_renders_the_summary_formatting_but_nothing_else(
        self, make_settings: SettingsFactory
    ) -> None:
        summary = Summary(
            VIDEO_ID, "en", "A **key** idea", ("Run `uv sync`", "[x](javascript:alert(1)) *ok*")
        )
        app = App(make_settings, ScriptedRunner(outcome=replace(RESULT, summary=summary)))
        job = app.start()

        html_text = app.client.get(f"/jobs/{job.job_id}").text

        assert '<p class="tldr">A <strong>key</strong> idea</p>' in html_text
        assert "<span>Run <code>uv sync</code></span>" in html_text
        assert "<span>[x](javascript:alert(1)) <em>ok</em></span>" in html_text
        assert not Page(html_text).find("a", href="javascript:alert(1)")

    def test_a_finished_job_offers_copy_download_and_a_new_video(
        self, make_settings: SettingsFactory
    ) -> None:
        summary = Summary(VIDEO_ID, "en", f"Gist {HOSTILE}", ("A **key** point",))
        result = replace(RESULT, summary=summary)
        app = App(make_settings, ScriptedRunner(outcome=result))
        job = app.start()

        html_text = app.client.get(f"/jobs/{job.job_id}").text

        page = Page(html_text)
        [copy] = page.find("button", **{"data-copy": "summary-markdown"})
        assert "hidden" in copy
        [download] = page.find("a", href=f"/jobs/{job.job_id}/summary.md")
        assert "download" in download
        [new_video] = page.find("a", href="/", **{"aria-label": "Summarize a new video"})
        assert new_video["class"] == "btn btn-ghost new-video"
        [toast] = page.find("div", role="status")
        assert "data-toast" in toast
        [markdown] = MARKDOWN_TEMPLATE_RE.findall(html_text)
        assert HOSTILE not in markdown
        assert html.unescape(markdown) == to_markdown(result)
        assert page.inline_code == []

    def test_a_running_job_has_no_result_actions(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings, hold=True)
        job = app.start()

        html_text = app.client.get(f"/jobs/{job.job_id}").text

        assert "summary-markdown" not in html_text
        assert "summary.md" not in html_text

    def test_a_failed_job_shows_the_safe_message(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings, ScriptedRunner(outcome=VideoTooLongError(7200)))
        job = app.start()

        html = app.client.get(f"/jobs/{job.job_id}").text

        assert "This video is longer than 2 hours, the most vidbrief summarizes." in html
        assert "Looking up the video" not in html
        assert "<code>jNQXAC9IVRw</code>" in html
        assert Page(html).find("a", href="/")
        assert "Try another link" in html

    def test_unknown_jobs_get_a_friendly_404_page(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings)

        response = app.client.get("/jobs/does-not-exist")

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/html")
        assert "This summary is no longer available" in response.text

    def test_loads_the_vendored_sse_extension_with_its_pinned_hash(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings, hold=True)
        job = app.start()

        page = Page(app.client.get(f"/jobs/{job.job_id}").text)

        [script] = page.find("script", src="/static/vendor/htmx-ext-sse-2.2.4.min.js")
        assert script["integrity"] == SSE_SHA384
        body = app.client.get("/static/vendor/htmx-ext-sse-2.2.4.min.js").content
        digest = base64.b64encode(hashlib.sha384(body).digest()).decode()
        assert f"sha384-{digest}" == SSE_SHA384


class TestMarkdownDownload:
    def test_a_finished_job_downloads_as_a_markdown_file(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings)
        job = app.start()

        response = app.client.get(f"/jobs/{job.job_id}/summary.md")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"
        assert response.headers["content-disposition"] == (
            'attachment; filename="vidbrief-jNQXAC9IVRw.md"'
        )
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.text == to_markdown(RESULT)

    def test_a_running_job_has_nothing_to_download_yet(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings, hold=True)
        job = app.start()

        response = app.client.get(f"/jobs/{job.job_id}/summary.md")

        assert response.status_code == 409
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text == "The summary is not ready."

    def test_a_failed_job_has_nothing_to_download(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings, ScriptedRunner(outcome=VideoTooLongError(7200)))
        job = app.start()

        response = app.client.get(f"/jobs/{job.job_id}/summary.md")

        assert response.status_code == 409

    def test_unknown_jobs_have_no_file(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings)

        response = app.client.get("/jobs/missing/summary.md")

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("text/plain")


class TestEvents:
    def test_a_finished_job_sends_its_final_state_then_ends(
        self, make_settings: SettingsFactory
    ) -> None:
        app = App(make_settings)
        job = app.start()

        response = app.client.get(f"/jobs/{job.job_id}/events")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [block for block in response.text.split("\r\n\r\n") if block.strip()]
        assert events[0].startswith("event: progress\r\n")
        assert "Gist." in events[0]
        assert events[-1].startswith("event: end")

    def test_a_failed_job_sends_the_error(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings, ScriptedRunner(outcome=VideoTooLongError(7200)))
        job = app.start()

        body = app.client.get(f"/jobs/{job.job_id}/events").text

        assert "This video is longer than 2 hours, the most vidbrief summarizes." in body

    def test_unknown_jobs_have_no_stream(self, make_settings: SettingsFactory) -> None:
        app = App(make_settings)

        assert app.client.get("/jobs/missing/events").status_code == 404


def test_htmx_shows_the_busy_message_in_the_form(make_settings: SettingsFactory) -> None:
    app = App(make_settings)

    [meta] = Page(app.client.get("/").text).find("meta", name="htmx-config")

    assert '{"code":"429","swap":true}' in (meta["content"] or "")


def test_stopping_the_server_reports_abandoned_jobs(
    make_settings: SettingsFactory, caplog: pytest.LogCaptureFixture
) -> None:
    app = App(make_settings, hold=True)

    with caplog.at_level(logging.WARNING, logger="vidbrief.web.jobs"), app.client:
        app.start()

    assert [r.message for r in caplog.records] == ["jobs abandoned at shutdown"]
