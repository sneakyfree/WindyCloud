"""Per-identity rate limiting middleware."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter keyed by identity_id.

    Limits authenticated requests per identity. Unauthenticated requests
    (health checks, etc.) are not rate limited.
    """

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _clean_window(self, key: str, now: float) -> None:
        cutoff = now - 60.0
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health/status endpoints
        if request.url.path in ("/health", "/api/v1/status"):
            return await call_next(request)

        # Extract identity from auth header if present
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return await call_next(request)

        # Use the token's first 16 chars as a rate limit key
        # (actual identity extraction happens in the route dependency)
        token = auth[7:]
        key = token[:16] if len(token) >= 16 else token

        now = time.monotonic()
        self._clean_window(key, now)

        if len(self._windows[key]) >= self.rpm:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a moment."},
                headers={"Retry-After": "60"},
            )

        self._windows[key].append(now)
        return await call_next(request)
