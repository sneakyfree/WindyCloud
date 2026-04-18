"""Live end-to-end tests against a running Eternitas Trust API.

These tests assert **actual HTTP behavior** — not mocks. They are skipped
cleanly when Eternitas isn't reachable at `ETERNITAS_URL`, so CI doesn't
flake on environment-dependent tests.

To run locally:

    # 1. Start Eternitas (postgres + redis + uvicorn):
    cd /Users/thewindstorm/eternitas && scripts/dev-start.sh
    # 2. Point us at it:
    export ETERNITAS_URL=http://localhost:8200   # or :8500 per Wave 4 spec
    # 3. Seed the DB with at least one known passport. Then:
    uv run pytest api/tests/integration/test_trust_live.py -v

Environment variables:
    ETERNITAS_URL              — base URL (default: taken from settings)
    ETERNITAS_TEST_PASSPORT    — a passport known to exist in the Eternitas DB
                                 (bot: ET*, operator: EH*). Required for the
                                 "known passport" assertions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import httpx
import pytest

from api.app.config import settings
from api.app.services.trust_client import (
    TrustClient,
    TrustInfo,
    _reset_trust_client_for_testing,
)

ETERNITAS_URL = os.environ.get("ETERNITAS_URL") or settings.eternitas_url
KNOWN_PASSPORT = os.environ.get("ETERNITAS_TEST_PASSPORT")
UNKNOWN_PASSPORT = "ET-99999-NEVERREAL"


def _eternitas_reachable() -> bool:
    """Quick probe — 200 or 404 both mean 'there's a server there'."""
    try:
        resp = httpx.get(f"{ETERNITAS_URL}/health", timeout=1.5)
        return resp.status_code < 500
    except (httpx.HTTPError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _eternitas_reachable(),
    reason=f"Eternitas not reachable at {ETERNITAS_URL} — start it per docstring",
)


# ---------------------------------------------------------------------------
# Real HTTP scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_passport_returns_full_contract():
    if not KNOWN_PASSPORT:
        pytest.skip("Set ETERNITAS_TEST_PASSPORT to a passport seeded in Eternitas.")
    _reset_trust_client_for_testing()
    client = TrustClient(base_url=ETERNITAS_URL, use_mock=False)

    info = await client.get_trust(KNOWN_PASSPORT)
    assert info is not None, f"{KNOWN_PASSPORT} not found in Eternitas"
    assert isinstance(info, TrustInfo)
    assert info.passport_number == KNOWN_PASSPORT
    # Contract guarantees
    assert info.status in ("active", "suspended", "revoked")
    assert info.band in ("exceptional", "good", "fair", "poor", "critical")
    assert info.clearance_level in (
        "registered",
        "verified",
        "cleared",
        "top_secret",
        "eternal",
    )
    assert 0 <= info.integrity_score <= 1000
    assert info.tier_multiplier >= 0.0
    assert info.cache_ttl_seconds > 0


@pytest.mark.asyncio
async def test_unknown_passport_returns_none():
    client = TrustClient(base_url=ETERNITAS_URL, use_mock=False)
    info = await client.get_trust(UNKNOWN_PASSPORT)
    assert info is None


@pytest.mark.asyncio
async def test_cache_hit_miss_headers():
    """Direct HTTP — the first call should miss, the second should hit."""
    if not KNOWN_PASSPORT:
        pytest.skip("Set ETERNITAS_TEST_PASSPORT.")
    async with httpx.AsyncClient(base_url=ETERNITAS_URL, timeout=5.0) as http:
        r1 = await http.get(f"/api/v1/trust/{KNOWN_PASSPORT}")
        r2 = await http.get(f"/api/v1/trust/{KNOWN_PASSPORT}")
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Either order is acceptable depending on server-side cache state at
    # test start — we just assert the header is present and uses the
    # documented vocabulary.
    cache_headers = {r1.headers.get("X-Trust-Cache"), r2.headers.get("X-Trust-Cache")}
    assert cache_headers.issubset({"hit", "miss", None})
    trust_cache_values = (
        r1.headers.get("X-Trust-Cache"),
        r2.headers.get("X-Trust-Cache"),
    )
    assert any(h == "hit" for h in trust_cache_values), "Expected a cache hit on the second call"


@pytest.mark.asyncio
async def test_unrecognised_prefix_returns_400():
    async with httpx.AsyncClient(base_url=ETERNITAS_URL, timeout=5.0) as http:
        resp = await http.get("/api/v1/trust/ZZ-not-a-passport")
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Client-side cache behavior + trust.changed-style invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_cache_repeats_single_http_call():
    """Two consecutive calls to our client should share the 5-min cache."""
    if not KNOWN_PASSPORT:
        pytest.skip("Set ETERNITAS_TEST_PASSPORT.")
    client = TrustClient(base_url=ETERNITAS_URL, use_mock=False)
    first = await client.get_trust(KNOWN_PASSPORT)
    assert first is not None
    second = await client.get_trust(KNOWN_PASSPORT)
    assert second is first  # identical object → came from cache


@pytest.mark.asyncio
async def test_invalidate_forces_refetch():
    """After invalidate(), the next call must hit the network again."""
    if not KNOWN_PASSPORT:
        pytest.skip("Set ETERNITAS_TEST_PASSPORT.")
    client = TrustClient(base_url=ETERNITAS_URL, use_mock=False)
    a = await client.get_trust(KNOWN_PASSPORT)
    client.invalidate(KNOWN_PASSPORT)
    b = await client.get_trust(KNOWN_PASSPORT)
    assert a is not None and b is not None
    assert a is not b  # different objects → went back to the server


# ---------------------------------------------------------------------------
# trust.changed webhook round-trip (simulated dispatch against our own app)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_changed_webhook_flushes_our_cache(monkeypatch):
    """Hand-craft a signed trust.changed delivery and confirm it flushes cache.

    We don't need Eternitas to actually dispatch the webhook for this — the
    consumer contract is the test subject. We prove: (1) the signature is
    verified, and (2) the trust client's cached entry is invalidated.
    """
    from httpx import ASGITransport, AsyncClient

    from api.app.db.engine import get_db
    from api.app.main import create_app
    from api.app.services.trust_client import get_trust_client

    secret = "live-test-trust-webhook-secret"
    monkeypatch.setattr(settings, "eternitas_webhook_secret", secret)

    # Seed the client cache
    client = get_trust_client()
    fake = TrustInfo(
        passport_number="ET-CACHE-ME",
        status="active",
        tier_multiplier=1.0,
    )
    client._cache["ET-CACHE-ME"] = (time.monotonic(), fake)
    assert "ET-CACHE-ME" in client._cache

    # Build a signed delivery
    body = json.dumps(
        {
            "event": "trust.changed",
            "passport_number": "ET-CACHE-ME",
            "reason": "integrity_band: good→fair",
            "old_band": "good",
            "new_band": "fair",
            "timestamp": "2026-04-16T20:11:03.118+00:00Z",
        }
    ).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    app = create_app()

    async def _db():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from api.app.db.models import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            yield sess
        await engine.dispose()

    app.dependency_overrides[get_db] = _db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/webhooks/trust/changed",
            content=body,
            headers={
                "X-Eternitas-Signature": sig,
                "X-Eternitas-Event": "trust.changed",
                "X-Eternitas-Timestamp": str(int(time.time())),
                "X-Eternitas-Delivery": "live-delivery-001",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "invalidated"
    assert "ET-CACHE-ME" not in client._cache
