"""CSRF tokens bound to a per-visitor cookie (signed double-submit pattern)."""

import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

logger = logging.getLogger(__name__)

CSRF_COOKIE = "vidbrief_csrf"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

_NONCE_BYTES = 32
_NONCE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
_FORM_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")
_EXPIRED_MESSAGE = "The form expired. Reload the page and try again."


@dataclass(frozen=True)
class CsrfToken:
    """A page token and the cookie nonce it was derived from."""

    nonce: str
    value: str


class CsrfProtector:
    """Issue and check CSRF tokens.

    The cookie holds a random nonce and pages embed an HMAC of it. A forged request from
    another site cannot read the cookie, so it cannot produce the matching token.
    """

    def __init__(self, key: bytes | None = None) -> None:
        # A key per server run is enough for a local app: restarting only invalidates
        # forms that were already open.
        self._key = key or secrets.token_bytes(32)

    def token_for(self, request: Request) -> CsrfToken:
        """Return the token to embed in a page for the visitor making ``request``.

        An existing well-formed nonce is reused, so pages open in other tabs keep working.
        """
        nonce = request.cookies.get(CSRF_COOKIE)
        if nonce is None or not _NONCE_PATTERN.fullmatch(nonce):
            nonce = secrets.token_urlsafe(_NONCE_BYTES)
        return CsrfToken(nonce=nonce, value=self._sign(nonce))

    @staticmethod
    def set_cookie(response: Response, token: CsrfToken) -> None:
        """Store the nonce behind ``token`` in the visitor's cookie."""
        # Not Secure: the app is served over plain HTTP on loopback.
        response.set_cookie(CSRF_COOKIE, token.nonce, path="/", httponly=True, samesite="strict")

    async def verify(self, request: Request) -> bool:
        """Whether ``request`` carries a token that matches its nonce cookie."""
        nonce = request.cookies.get(CSRF_COOKIE)
        if nonce is None or not _NONCE_PATTERN.fullmatch(nonce):
            return False
        token = request.headers.get(CSRF_HEADER)
        if token is None and request.headers.get("content-type", "").startswith(
            _FORM_CONTENT_TYPES
        ):
            value = (await request.form()).get(CSRF_FIELD)
            token = value if isinstance(value, str) else None
        if token is None:
            return False
        return hmac.compare_digest(token.encode(), self._sign(nonce).encode())

    def _sign(self, nonce: str) -> str:
        digest = hmac.new(self._key, nonce.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def require_csrf(request: Request) -> None:
    """FastAPI dependency that rejects requests without a valid CSRF token.

    Raises:
        HTTPException: 403 when the token is missing or does not match.
    """
    protector: CsrfProtector = request.app.state.csrf
    if not await protector.verify(request):
        logger.warning("request blocked", extra={"reason": "csrf_token_invalid"})
        raise HTTPException(status_code=403, detail=_EXPIRED_MESSAGE)
