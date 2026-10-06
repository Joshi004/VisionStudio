"""Origin check for state-changing requests.

Section 3.7 of ANALYSIS.md asks for localhost-only safeguards; Phase 1 of
ITERATION_1_PHASES.md (Section 5.9's "Added here" note) explains why a
Host check alone is not enough: browsers send `multipart/form-data` POSTs
to other origins without a CORS preflight, so "no CORS headers" alone does
not stop another site's page from submitting to this API through the
user's browser. This middleware rejects any non-safe request whose Origin
header names a different host or port than the Host header.

GET, HEAD and OPTIONS are exempt because they must not have side effects.
A request with no Origin header at all (curl, server-to-server, or an
older browser) is let through for the Origin check specifically — the
TrustedHostMiddleware ahead of this one is what blocks requests to a
wrong Host.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DEFAULT_PORT_BY_SCHEME = {"http": 80, "https": 443}


def _header_value(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def _host_and_port(value: str, default_scheme: str) -> tuple[str, int | None]:
    """Splits a `host[:port]` or `scheme://host[:port]` value.

    A missing port is filled in from `default_scheme`'s standard port, so
    `https://example.com` and `https://example.com:443` compare equal.
    """
    netloc = value if "//" in value else f"//{value}"
    parsed = urlsplit(netloc)
    port = parsed.port if parsed.port is not None else _DEFAULT_PORT_BY_SCHEME.get(default_scheme)
    return (parsed.hostname or "").lower(), port


class OriginCheckMiddleware:
    """Plain ASGI middleware: 403s a cross-origin, state-changing request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        origin = _header_value(scope, b"origin")
        if origin is None:
            await self.app(scope, receive, send)
            return

        origin_scheme = urlsplit(origin).scheme or "http"
        origin_host, origin_port = _host_and_port(origin, origin_scheme)
        host_header = _header_value(scope, b"host") or ""
        host_host, host_port = _host_and_port(host_header, "http")

        if (origin_host, origin_port) != (host_host, host_port):
            response = JSONResponse(
                {"detail": "Cross-origin request rejected: Origin does not match Host."},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
