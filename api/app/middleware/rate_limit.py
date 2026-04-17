"""Per-identity rate limiting middleware with per-route overrides.

Wave 7 G20: pre-fix this was a flat 120 req/min/IP across every
endpoint that carried a Bearer token. That meant a legitimate
product-backend pushing archive backups competed with adversarial
probe traffic, and a single IP could burst 120 uploads per minute —
each potentially up to `max_upload_size` in size, i.e. 30 GB/min of
raw request body from one source.

The bucket shape now:

  - Per-route tiers:
      writes / money       →  lower  (10–30 per minute)
      reads                →  default (120 per minute)
      webhooks             →  exempt (Eternitas retries reuse source IP;
                              signatures carry the anti-abuse weight)
  - Keyed by Bearer-token hash when present; falls back to the
    client IP for anonymous requests (so a raw-IP scraper can't
    silently bypass by not sending a token).
  - Requests that have no token AND no IP (unlikely but defensive)
    are rate-limited as a shared "anon" bucket.
"""

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

# Per-route per-minute caps. First matching prefix wins.
# None → exempt from rate limiting on that path.
ROUTE_LIMITS: list[tuple[str, int | None]] = [
    # Exempt: inbound webhooks. Eternitas retries use the same source IP
    # and signature verification is already the expensive step.
    ("/api/v1/webhooks/", None),
    # Health + status already skipped in the dispatch body.
    # Writes / money — tight limits to cut blast radius per IP.
    ("/api/v1/billing/allocate", 10),
    ("/api/v1/billing/plan/upgrade", 10),
    ("/api/v1/storage/upload", 30),
    ("/api/v1/archive/", 30),
    ("/api/v1/compute/stt", 30),
    ("/api/v1/servers/create", 10),
    ("/api/v1/servers/deploy-fly", 10),
    # Identity bridge — service-token calls, cheap but rate-limit as
    # defense in depth if token ever leaks.
    ("/api/v1/identity/", 60),
]

DEFAULT_LIMIT_PER_MINUTE = 120


def limit_for_path(path: str, default: int) -> int | None:
    """Return the per-minute limit for this request path, or None for exempt."""
    for prefix, limit in ROUTE_LIMITS:
        if path == prefix or path.startswith(prefix):
            return limit
    return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter, keyed per-caller and per-route.

    Window is 60 seconds. One counter per (caller, route-tier) pair so
    a write burst on /upload doesn't lock the caller out of read
    endpoints (or vice versa).
    """

    def __init__(self, app, requests_per_minute: int = DEFAULT_LIMIT_PER_MINUTE):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._request_count = 0

    def _clean_window(self, key: str, now: float) -> None:
        cutoff = now - 60.0
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

    def _prune_stale_keys(self, now: float) -> None:
        cutoff = now - 120.0
        stale = [k for k, ts in self._windows.items() if not ts or ts[-1] < cutoff]
        for k in stale:
            del self._windows[k]

    def _caller_id(self, request: Request) -> str:
        """Stable per-caller id. Bearer-token hash if present, else IP.

        Falls back to "anon" if the request has neither — shouldn't
        happen in practice but keeps the limiter from letting through
        truly unidentifiable traffic unbucketed.
        """
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            return "t:" + hashlib.sha256(token.encode()).hexdigest()[:16]
        # Service-token callers (internal product backends) also get
        # bucketed so a leaked service token can't burn uploads for
        # everyone.
        svc = request.headers.get("x-service-token", "")
        if svc:
            return "s:" + hashlib.sha256(svc.encode()).hexdigest()[:16]
        client = request.client
        if client and client.host:
            return "ip:" + client.host
        return "anon"

    def _bucket_tier(self, limit: int | None) -> str:
        """Collapse tiers so one caller gets separate per-tier counters.

        `limit` of None means exempt — short-circuited before we get here.
        """
        return f"{limit}"

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Health/status never rate-limited.
        if path in ("/health", "/api/v1/status"):
            return await call_next(request)

        limit = limit_for_path(path, self.rpm)
        if limit is None:
            return await call_next(request)

        key = self._caller_id(request) + "|" + self._bucket_tier(limit)

        now = time.monotonic()
        self._clean_window(key, now)

        self._request_count += 1
        if self._request_count % _CLEANUP_INTERVAL == 0:
            self._prune_stale_keys(now)

        if len(self._windows[key]) >= limit:
            logger.warning(
                "Rate limit exceeded: key=%s path=%s limit=%d",
                key[:24],
                path,
                limit,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a moment."},
                headers={"Retry-After": "60"},
            )

        self._windows[key].append(now)
        return await call_next(request)
