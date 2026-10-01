"""Pages and form handling of the web interface."""

import logging
import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from vidbrief.config import Settings
from vidbrief.domain.errors import VidbriefError
from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES, summary_language_name
from vidbrief.domain.video import parse_youtube_url
from vidbrief.web.csrf import CSRF_FIELD, CsrfProtector, require_csrf
from vidbrief.web.languages import LANGUAGE_OPTIONS
from vidbrief.web.server import url_host

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
_LANGUAGES_BY_CODE = {option.code: option for option in LANGUAGE_OPTIONS}

# Windows takes MIME types from the registry, where .js is sometimes text/plain; with
# nosniff, browsers would then refuse to run the scripts.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> Response:
    """Show the form where users paste a link and pick the summary language."""
    return _home_page(request)


@router.post("/summaries", response_class=HTMLResponse, dependencies=[Depends(require_csrf)])
def create_summary(
    request: Request,
    url: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
) -> Response:
    """Validate a summary request.

    HTMX requests get fragments: only the error text on failure (status 422), or a panel
    that replaces the form on success. Plain form posts get the whole page back, so the
    form also works without JavaScript. Raw input is never echoed back.
    """
    from_htmx = request.headers.get("hx-request") == "true"
    try:
        video_id = parse_youtube_url(url)
        summary_language_name(language)
    except VidbriefError as error:
        logger.info("summary request rejected", extra={"reason": error.reason})
        if from_htmx:
            return _TEMPLATES.TemplateResponse(
                request,
                "partials/form_error.html",
                {"message": error.user_message},
                status_code=422,
            )
        return _home_page(request, error=error.user_message, language=language, status_code=422)

    logger.info("summary request accepted", extra={"video_id": video_id.value})
    accepted = {"video_id": video_id.value, "language": _LANGUAGES_BY_CODE[language]}
    if from_htmx:
        return _TEMPLATES.TemplateResponse(
            request,
            "partials/accepted.html",
            {"accepted": accepted},
            headers={"HX-Retarget": "#summary-form", "HX-Reswap": "outerHTML"},
        )
    return _home_page(request, accepted=accepted)


def describe_duration(seconds: int) -> str:
    """Render a duration limit the way people say it, e.g. ``2 hours`` or ``90 minutes``."""
    if seconds >= 3600 and seconds % 3600 == 0:
        return _plural(seconds // 3600, "hour")
    if seconds >= 60:
        return _plural(seconds // 60, "minute")
    return _plural(seconds, "second")


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"


def _home_page(
    request: Request,
    *,
    error: str | None = None,
    accepted: dict[str, Any] | None = None,
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
            "address": f"{url_host(settings.host)}:{settings.port}",
            "max_duration": describe_duration(settings.max_video_duration_seconds),
            "languages": LANGUAGE_OPTIONS,
            "selected_language": selected or settings.default_summary_language,
            "csrf_field": CSRF_FIELD,
            "csrf_token": token.value,
            "error": error,
            "accepted": accepted,
        },
        status_code=status_code,
    )
    csrf.set_cookie(response, token)
    return response
