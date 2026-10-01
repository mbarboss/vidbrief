"""FastAPI application factory."""

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from vidbrief.config import Settings
from vidbrief.services.pipeline import SummaryRunner
from vidbrief.web.csrf import CsrfProtector
from vidbrief.web.security import CrossOriginGuardMiddleware, SecurityHeadersMiddleware
from vidbrief.web.server import url_host

_LOOPBACK_NAMES = ("localhost", "127.0.0.1")


def create_app(
    settings: Settings, runner: SummaryRunner, *, csrf: CsrfProtector | None = None
) -> FastAPI:
    """Build the web app around an already validated configuration and pipeline."""
    app = FastAPI(title="vidbrief", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.runner = runner
    app.state.csrf = csrf or CsrfProtector()

    # Starlette runs the last added middleware first, so the security headers also reach
    # the responses the host and origin checks reject.
    app.add_middleware(CrossOriginGuardMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(settings))
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def allowed_hosts(settings: Settings) -> list[str]:
    """Host header values the app answers to.

    Accepting only loopback names stops DNS rebinding, where a malicious site points its
    own domain at 127.0.0.1 to reach the app from the visitor's browser.
    """
    host = url_host(settings.host)
    return [host, *(name for name in _LOOPBACK_NAMES if name != host)]
