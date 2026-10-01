"""ASGI middleware that hardens every HTTP response and blocks cross-site writes."""

import logging

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        # Video thumbnails are the only third-party resource the pages load.
        "img-src 'self' https://i.ytimg.com",
        "connect-src 'self'",
        "font-src 'self'",
        "form-action 'self'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ]
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    # Older browsers ignore frame-ancestors, so clickjacking needs the legacy header too.
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
_DEFAULT_CACHE_CONTROL = "no-store"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# "none" means the user started the request (address bar, bookmark), not another site.
_TRUSTED_FETCH_SITES = frozenset({"same-origin", "none"})


class SecurityHeadersMiddleware:
    """Add a strict Content-Security-Policy and related headers to every response.

    Pages are not cached unless a route sets its own ``Cache-Control``, because they carry
    per-visitor CSRF tokens and summaries.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers[name] = value
                if "cache-control" not in headers:
                    headers["Cache-Control"] = _DEFAULT_CACHE_CONTROL
            await send(message)

        await self.app(scope, receive, send_with_headers)


class CrossOriginGuardMiddleware:
    """Reject state-changing requests that a browser sent on behalf of another site.

    ``Sec-Fetch-Site`` is trusted when present because browsers set it and pages cannot
    forge it; otherwise ``Origin`` must match the requested host. Requests with neither
    header do not come from a browser, so they cannot be cross-site forgeries.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        if _is_cross_origin(Headers(scope=scope)):
            logger.warning("request blocked", extra={"reason": "cross_origin_request"})
            response = PlainTextResponse("Cross-origin request blocked.", status_code=403)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _is_cross_origin(headers: Headers) -> bool:
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site not in _TRUSTED_FETCH_SITES
    origin = headers.get("origin")
    if origin is None:
        return False
    return origin != f"http://{headers.get('host', '')}"
