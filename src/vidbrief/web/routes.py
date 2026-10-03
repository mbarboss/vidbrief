"""Pages and form handling of the web interface."""

import logging
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sse_starlette import EventSourceResponse, ServerSentEvent

from vidbrief.config import Settings
from vidbrief.domain.durations import describe_duration
from vidbrief.domain.errors import InvalidVideoUrlError, TooManyJobsError, VidbriefError
from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES, summary_language_name
from vidbrief.domain.models import TranscriptSource
from vidbrief.domain.video import parse_youtube_url
from vidbrief.services.inline_markdown import to_inline_html
from vidbrief.services.report import to_markdown
from vidbrief.web.csrf import CSRF_FIELD, CsrfProtector, require_csrf
from vidbrief.web.jobs import JobManager, JobSnapshot, JobStatus
from vidbrief.web.languages import LANGUAGE_OPTIONS
from vidbrief.web.server import url_host
from vidbrief.web.timeline import build_timeline, format_clock, format_seconds

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
_LANGUAGES_BY_CODE = {option.code: option for option in LANGUAGE_OPTIONS}
_SOURCE_LABELS = {
    TranscriptSource.MANUAL_CAPTIONS: "From captions",
    TranscriptSource.AUTO_CAPTIONS: "From auto captions",
    TranscriptSource.SPEECH_TO_TEXT: "From the audio",
}
# Keeps idle connections alive through the browser and any local proxy.
_SSE_PING_SECONDS = 15

# Windows takes MIME types from the registry, where .js is sometimes text/plain; with
# nosniff, browsers would then refuse to run the scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")

router = APIRouter()


def _inline_markdown(text: str) -> Markup:
    # Safe to mark: to_inline_html escapes everything and nh3 keeps only strong/em/code.
    return Markup(to_inline_html(text))  # noqa: S704


_TEMPLATES.env.filters["inline_markdown"] = _inline_markdown


@router.get("/", response_class=HTMLResponse)
def home(request: Request, url: str = "", language: str = "") -> Response:
    """Show the form where users paste a link and pick the summary language.

    ``url`` and ``language`` come from a failed job's "Try again" link and only fill in
    the form. A link that does not parse and a language outside the allowlist are
    ignored, never echoed; a valid link is replaced by its canonical form.
    """
    try:
        canonical_url = parse_youtube_url(url).canonical_url if url else None
    except InvalidVideoUrlError:
        canonical_url = None
    return _home_page(request, url=canonical_url, language=language)


@router.post("/summaries", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def create_summary(
    request: Request,
    url: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
) -> Response:
    """Validate a summary request and start its job.

    HTMX requests get ``HX-Redirect`` to the job page, or only the error text (422, or 429
    when another summary is running) to show under the field. Plain form posts get a 303
    redirect or the whole page with the error, so the form works without JavaScript. Raw
    input is never echoed back.
    """
    from_htmx = request.headers.get("hx-request") == "true"
    try:
        video_id = parse_youtube_url(url)
        summary_language_name(language)
        job_id = _jobs(request).submit(video_id, language)
    except VidbriefError as error:
        logger.info("summary request rejected", extra={"reason": error.reason})
        status_code = 429 if isinstance(error, TooManyJobsError) else 422
        if from_htmx:
            return _TEMPLATES.TemplateResponse(
                request,
                "partials/form_error.html",
                {"message": error.user_message},
                status_code=status_code,
            )
        return _home_page(
            request, error=error.user_message, language=language, status_code=status_code
        )

    job_url = f"/jobs/{job_id}"
    if from_htmx:
        return Response(headers={"HX-Redirect": job_url})
    return RedirectResponse(job_url, status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str) -> Response:
    """Show a job: live progress while it runs, then its summary or its error."""
    jobs = _jobs(request)
    job = jobs.get(job_id)
    if job is None:
        return _TEMPLATES.TemplateResponse(
            request, "job_missing.html", _page_context(request), status_code=404
        )
    snapshot = job.snapshot()
    return _TEMPLATES.TemplateResponse(
        request, "job.html", {**_page_context(request), **_job_context(snapshot, jobs.now())}
    )


@router.get("/jobs/{job_id}/summary.md", response_model=None)
def job_markdown(request: Request, job_id: str) -> Response:
    """Download a finished summary as a Markdown file.

    The file name uses only the video ID, never the untrusted title. Jobs that are still
    running or that failed get 409.
    """
    job = _jobs(request).get(job_id)
    if job is None:
        return PlainTextResponse("Not Found", status_code=404)
    snapshot = job.snapshot()
    if snapshot.result is None:
        return PlainTextResponse("The summary is not ready.", status_code=409)
    filename = f"vidbrief-{snapshot.video_id.value}.md"
    return Response(
        to_markdown(snapshot.result),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}/events", response_model=None)
def job_events(request: Request, job_id: str) -> Response:
    """Stream the job's rendered state as Server-Sent Events until it finishes.

    Every event carries the whole job body, so a reconnecting browser is never out of
    date. A final ``end`` event tells HTMX to close the connection.
    """
    jobs = _jobs(request)
    job = jobs.get(job_id)
    if job is None:
        return PlainTextResponse("Not Found", status_code=404)
    body = _TEMPLATES.env.get_template("partials/job_body.html")

    async def events() -> AsyncIterator[ServerSentEvent]:
        async for snapshot in job.watch():
            html = body.render(_job_context(snapshot, jobs.now()))
            yield ServerSentEvent(html, event="progress")
        yield ServerSentEvent("", event="end")

    return EventSourceResponse(events(), ping=_SSE_PING_SECONDS)


def _jobs(request: Request) -> JobManager:
    jobs: JobManager = request.app.state.jobs
    return jobs


def _page_context(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {"address": f"{url_host(settings.host)}:{settings.port}"}


def _job_context(snapshot: JobSnapshot, now: float) -> dict[str, Any]:
    video = snapshot.result.metadata if snapshot.result else snapshot.video
    return {
        "job": snapshot,
        "running": snapshot.status is JobStatus.RUNNING,
        "video": video,
        "video_length": format_clock(video.duration_seconds) if video else None,
        "timeline": build_timeline(snapshot),
        "elapsed_seconds": int(snapshot.elapsed_seconds(now)),
        "elapsed_clock": format_clock(int(snapshot.elapsed_seconds(now))),
        "took": format_seconds(snapshot.elapsed_seconds(now)),
        "language": _LANGUAGES_BY_CODE[snapshot.language],
        "source": _SOURCE_LABELS[snapshot.result.transcript_source] if snapshot.result else None,
        "markdown": to_markdown(snapshot.result) if snapshot.result else None,
        "retry_url": _retry_url(snapshot) if snapshot.retryable else None,
    }


def _retry_url(snapshot: JobSnapshot) -> str:
    query = urlencode({"url": snapshot.video_id.canonical_url, "language": snapshot.language})
    return f"/?{query}"


def _home_page(
    request: Request,
    *,
    error: str | None = None,
    url: str | None = None,
    language: str | None = None,
    status_code: int = 200,
) -> Response:
    settings: Settings = request.app.state.settings
    csrf: CsrfProtector = request.app.state.csrf
    token = csrf.token_for(request)
    selected = language if language in SUPPORTED_SUMMARY_LANGUAGES else None
    response = _TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            **_page_context(request),
            "max_duration": describe_duration(settings.max_video_duration_seconds),
            "languages": LANGUAGE_OPTIONS,
            "selected_language": selected or settings.default_summary_language,
            "csrf_field": CSRF_FIELD,
            "csrf_token": token.value,
            "error": error,
            "url": url,
        },
        status_code=status_code,
    )
    csrf.set_cookie(response, token)
    return response
