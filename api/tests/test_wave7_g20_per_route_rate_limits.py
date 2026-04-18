"""GAP G20: per-route rate limits.

Pre-G20 the middleware applied a flat 120 req/min/IP and only rate-limited
callers that presented a Bearer token. That meant:

  - Webhook endpoints (no Bearer) competed silently with the limiter
  - A single IP could burst 120 uploads / minute → 30 GB/min of raw
    request body from one source before hitting the global cap
  - A compromised service token could fire 120 allocate calls per IP

Post-G20:

  - Webhooks exempt (Eternitas retries reuse source IP; signatures
    carry the anti-abuse weight)
  - /upload + /archive/* limited to 30/min per caller
  - /billing/allocate + /plan/upgrade + server CRUD at 10/min
  - Anonymous callers now bucketed by IP, not silently ignored
  - Per-tier counters — a write burst doesn't lock the caller out of
    reads (or vice versa)
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from api.app.middleware.rate_limit import (
    DEFAULT_LIMIT_PER_MINUTE,
    ROUTE_LIMITS,
    RateLimitMiddleware,
    limit_for_path,
)


# ---------------------------------------------------------------------------
# Route → limit table semantics
# ---------------------------------------------------------------------------

def test_webhook_paths_are_exempt():
    for path in (
        "/api/v1/webhooks/identity/created",
        "/api/v1/webhooks/passport/revoked",
        "/api/v1/webhooks/trust/changed",
    ):
        assert limit_for_path(path, DEFAULT_LIMIT_PER_MINUTE) is None, (
            f"{path} must be exempt — Eternitas retries share source IP"
        )


def test_writes_are_tighter_than_default():
    assert limit_for_path("/api/v1/storage/upload", DEFAULT_LIMIT_PER_MINUTE) == 30
    assert limit_for_path("/api/v1/archive/chat", DEFAULT_LIMIT_PER_MINUTE) == 30
    assert limit_for_path("/api/v1/billing/allocate", DEFAULT_LIMIT_PER_MINUTE) == 10


def test_unknown_path_uses_default():
    assert (
        limit_for_path("/api/v1/something/new", DEFAULT_LIMIT_PER_MINUTE)
        == DEFAULT_LIMIT_PER_MINUTE
    )


def test_health_paths_never_even_enter_the_table():
    # These are short-circuited inside dispatch before limit_for_path runs,
    # so limit_for_path returns the default here — that's fine.
    # This test documents the dispatch-level skip contract.
    assert limit_for_path("/health", 0) == 0
    assert limit_for_path("/api/v1/status", 0) == 0


# ---------------------------------------------------------------------------
# Middleware behaviour end-to-end
# ---------------------------------------------------------------------------

def _make_app_with_middleware(rpm: int = DEFAULT_LIMIT_PER_MINUTE):
    """Build a bare FastAPI app with just the rate-limit middleware and
    a handful of routes so we can hammer it without pulling the whole
    windy-cloud stack."""
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=rpm)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/v1/storage/files")
    async def list_files():
        return {"files": []}

    @app.post("/api/v1/storage/upload")
    async def upload():
        return {"uploaded": True}

    @app.post("/api/v1/webhooks/identity/created")
    async def webhook():
        return {"received": True}

    @app.post("/api/v1/billing/allocate")
    async def allocate():
        return {"allocated": True}

    return app


@pytest.mark.asyncio
async def test_webhook_endpoints_are_never_rate_limited():
    app = _make_app_with_middleware(rpm=5)  # tight for the rest, exempt for webhooks
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Burst well past any reasonable limit.
        for _ in range(20):
            resp = await ac.post("/api/v1/webhooks/identity/created")
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_upload_honours_its_30rpm_cap():
    app = _make_app_with_middleware()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 30 calls should all succeed; the 31st hits the wall.
        for i in range(30):
            resp = await ac.post(
                "/api/v1/storage/upload",
                headers={"Authorization": "Bearer rate-test-token"},
            )
            assert resp.status_code == 200, f"call #{i} unexpectedly 429'd"

        blocked = await ac.post(
            "/api/v1/storage/upload",
            headers={"Authorization": "Bearer rate-test-token"},
        )
        assert blocked.status_code == 429
        assert blocked.headers.get("retry-after") == "60"


@pytest.mark.asyncio
async def test_allocate_honours_its_10rpm_cap():
    app = _make_app_with_middleware()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for i in range(10):
            resp = await ac.post(
                "/api/v1/billing/allocate",
                headers={"X-Service-Token": "shared-secret-cov"},
            )
            assert resp.status_code == 200, f"call #{i} 429'd early"

        blocked = await ac.post(
            "/api/v1/billing/allocate",
            headers={"X-Service-Token": "shared-secret-cov"},
        )
        assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_read_bucket_separate_from_write_bucket():
    """Hitting /upload 30× mustn't also block /files reads for the same caller."""
    app = _make_app_with_middleware()
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer mixed-caller"}

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Burn the write bucket.
        for _ in range(30):
            await ac.post("/api/v1/storage/upload", headers=headers)

        blocked_write = await ac.post("/api/v1/storage/upload", headers=headers)
        assert blocked_write.status_code == 429

        # Read bucket should be unaffected.
        read = await ac.get("/api/v1/storage/files", headers=headers)
        assert read.status_code == 200


@pytest.mark.asyncio
async def test_anonymous_callers_bucketed_by_ip():
    """Pre-G20 unauthenticated calls silently skipped the limiter.
    Post-G20 they bucket by client IP (TestClient reports 'testclient')."""
    # Only 5/min on the default bucket so we can burn through without
    # pushing tens of calls through the async test client.
    app = _make_app_with_middleware(rpm=5)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(5):
            # GET on a path that falls through to the DEFAULT bucket
            # (not listed in ROUTE_LIMITS → uses rpm=5).
            resp = await ac.get("/api/v1/storage/files")
            assert resp.status_code == 200

        # 6th anon call must 429 on the default bucket.
        blocked = await ac.get("/api/v1/storage/files")
        assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_health_endpoint_never_rate_limited():
    app = _make_app_with_middleware(rpm=2)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for _ in range(10):
            resp = await ac.get("/health")
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_different_callers_get_separate_buckets():
    app = _make_app_with_middleware()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Caller A burns their upload bucket.
        for _ in range(30):
            r = await ac.post(
                "/api/v1/storage/upload",
                headers={"Authorization": "Bearer alice-token"},
            )
            assert r.status_code == 200
        blocked = await ac.post(
            "/api/v1/storage/upload",
            headers={"Authorization": "Bearer alice-token"},
        )
        assert blocked.status_code == 429

        # Caller B is completely separate.
        r = await ac.post(
            "/api/v1/storage/upload",
            headers={"Authorization": "Bearer bob-token"},
        )
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_service_token_callers_get_own_bucket():
    """A compromised service token can't silently burn all service-token
    callers' quota — each token hashes to its own bucket."""
    app = _make_app_with_middleware()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Token-A burns /allocate.
        for _ in range(10):
            r = await ac.post(
                "/api/v1/billing/allocate",
                headers={"X-Service-Token": "token-A"},
            )
            assert r.status_code == 200
        blocked = await ac.post(
            "/api/v1/billing/allocate",
            headers={"X-Service-Token": "token-A"},
        )
        assert blocked.status_code == 429

        # Token-B unaffected.
        r = await ac.post(
            "/api/v1/billing/allocate",
            headers={"X-Service-Token": "token-B"},
        )
        assert r.status_code == 200
