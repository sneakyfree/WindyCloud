"""Security headers middleware (Wave 14 P1).

The 2026-04-19 white-glove smoke report flagged that production Cloud
responses carried no security headers — no HSTS, no X-Content-Type-
Options, no X-Frame-Options, no CSP, no Referrer-Policy, no Permissions-
Policy. Certbot's `options-ssl-nginx.conf` sets cipher suites only; the
nginx site config has no add_header directives; FastAPI emits none by
default. This middleware closes that gap at the app layer so every
response (including error responses rendered by FastAPI before they
reach nginx) gets a conservative default set.

Headers chosen:

  - Strict-Transport-Security — 1-year HSTS with subdomains. Browsers
    that have visited cloud.windyword.ai once will refuse http:// on
    every Windy subdomain thereafter, closing a downgrade-attack
    window. No `preload` — we don't want to commit the apex to HSTS
    preload without a Grant-owned rollout plan.
  - X-Content-Type-Options: nosniff — blocks MIME-type sniffing.
  - X-Frame-Options: DENY — belt-and-braces with CSP frame-ancestors.
  - Referrer-Policy: strict-origin-when-cross-origin — bounds referrer
    leaks while keeping same-origin analytics usable.
  - Permissions-Policy — kill-switch for every sensor / payment /
    geolocation API we don't use.
  - Content-Security-Policy — default-deny with targeted allowances for
    the static landing page (/ and /static/*). The PWA manifest loads
    fonts from the same origin; inline styles in the landing page
    require `'unsafe-inline'` on style-src (the alternative, nonces,
    would need a templating layer we don't have and isn't worth the
    footprint for one static page).

Middleware uses `setdefault` so a route that legitimately overrides a
header (e.g. Content-Disposition on an export download, or a different
CSP for a specific HTML surface) can still do so — we only populate
when the response doesn't already have the header.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_CSP = (
    "default-src 'none'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "manifest-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

_PERMISSIONS_POLICY = (
    "geolocation=(), microphone=(), camera=(), payment=(), "
    "accelerometer=(), gyroscope=(), magnetometer=(), usb=()"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set conservative defaults on every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers
        # `setdefault` preserves any value a route has already set.
        headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", _PERMISSIONS_POLICY)
        headers.setdefault("Content-Security-Policy", _CSP)
        return response
