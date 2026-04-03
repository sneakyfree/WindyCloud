"""Per-identity rate limiting middleware with TTL cleanup."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Cleanup stale keys every N requests
_CLEANUP_INTERVAL = 500


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter keyed by identity.

    Uses the full Bearer token as the rate limit key (not just a prefix),
    and periodically prunes stale entries to prevent memory leaks.
    """

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._request_count = 0

    def _clean_window(self, key: str, now: float) -> None:
        cutoff = now - 60.0
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

    def _prune_stale_keys(self, now: float) -> None:
        """Remove keys with no recent activity to prevent unbounded memory growth."""
        cutoff = now - 120.0  # 2 minutes of inactivity
        stale = [k for k, ts in self._windows.items() if not ts or ts[-1] < cutoff]
        for k in stale:
            del self._windows[k]

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health/status endpoints
        if request.url.path in ("/health", "/api/v1/status"):
            return await call_next(request)

        # Extract identity from auth header if present
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return await call_next(request)

        # Hash the token to save memory (full JWTs are ~800 bytes)
        token = auth[7:]
        key = hashlib.sha256(token.encode()).hexdigest()[:16]

        now = time.monotonic()
        self._clean_window(key, now)

        # Periodic stale key cleanup
        self._request_count += 1
        if self._request_count % _CLEANUP_INTERVAL == 0:
            self._prune_stale_keys(now)

        if len(self._windows[key]) >= self.rpm:
            logger.warning("Rate limit exceeded for key %s...", key[:8])
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a moment."},
                headers={"Retry-After": "60"},
            )

        self._windows[key].append(now)
        return await call_next(request)
