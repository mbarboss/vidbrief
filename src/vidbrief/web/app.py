"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from vidbrief.config import Settings
from vidbrief.services.pipeline import SummaryRunner
from vidbrief.web.csrf import CsrfProtector
from vidbrief.web.jobs import JobManager
from vidbrief.web.routes import STATIC_DIR, router
from vidbrief.web.security import CrossOriginGuardMiddleware, SecurityHeadersMiddleware
from vidbrief.web.server import url_host

_LOOPBACK_NAMES = ("localhost", "127.0.0.1")


def create_app(
    settings: Settings,
    runner: SummaryRunner,
    *,
    csrf: CsrfProtector | None = None,
    jobs: JobManager | None = None,
) -> FastAPI:
    """Build the web app around an already validated configuration and pipeline."""
    job_manager = jobs or JobManager(runner, max_concurrent=settings.max_concurrent_jobs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        job_manager.shutdown()

    app = FastAPI(
        title="vidbrief", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.runner = runner
    app.state.csrf = csrf or CsrfProtector()
    app.state.jobs = job_manager

    # Starlette runs the last added middleware first, so the security headers also reach
    # the responses the host and origin checks reject.
    app.add_middleware(CrossOriginGuardMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(settings))
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.exception_handler(StarletteHTTPException)(_plain_text_error)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


async def _plain_text_error(request: Request, exc: StarletteHTTPException) -> Response:
    # The pages are HTML, not a JSON API: HTMX shows this text in the form's error slot.
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code, headers=exc.headers)


def allowed_hosts(settings: Settings) -> list[str]:
    """Host header values the app answers to.

    Accepting only loopback names stops DNS rebinding, where a malicious site points its
    own domain at 127.0.0.1 to reach the app from the visitor's browser.
    """
    host = url_host(settings.host)
    return [host, *(name for name in _LOOPBACK_NAMES if name != host)]
