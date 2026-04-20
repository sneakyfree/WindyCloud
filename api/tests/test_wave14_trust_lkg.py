"""Wave 14 PR5 — last-known-good fail-soft for TrustClient.

Pre-G6 in-process cache served stale trust when an Eternitas refresh
5xx'd. G6 (Redis) strictly honoured TTLs and lost that semantic. Wave
14 restores it via a second `trust:lkg:{passport}` keyspace with a
longer TTL. Successful fetches write to both; `invalidate()` clears
both.

These tests lock down:
  - 5xx after successful prime → LKG served.
  - Network error after successful prime → LKG served.
  - 429 does NOT fail-soft (rate-limit is caller's problem).
  - 404 does NOT fail-soft (passport explicitly removed).
  - invalidate() clears LKG too.
  - LKG survives longer than primary TTL.
  - Corrupt LKG blob is logged + deleted + returns None.
"""

from __future__ import annotations

import time

import httpx
import pytest

from api.app.services.cache_backend import InMemoryCacheBackend
from api.app.services.trust_client import (
    TrustClient,
    TrustInfo,
    _LKG_MULTIPLIER,
    _trust_cache_key,
    _trust_lkg_key,
)


def _stub_httpx(monkeypatch, responses):
    """Each entry is (status, json_body_or_None) OR an Exception instance."""
    from api.app.services import trust_client as tc_mod

    class _Response:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body
            self.text = "stub"

        def json(self):
            return self._body

    class _AsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            entry = responses.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return _Response(*entry)

    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _AsyncClient)


# ---------------------------------------------------------------------------
# LKG fail-soft on 5xx / network errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_5xx_serves_lkg_after_prime(monkeypatch):
    _stub_httpx(
        monkeypatch,
        [
            (
                200,
                {
                    "passport_number": "ET-LKG-500",
                    "status": "active",
                    "band": "good",
                    "tier_multiplier": 2.0,
                    "cache_ttl_seconds": 300,
                },
            ),
            (500, None),
        ],
    )
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=1, backend=backend
    )
    first = await client.get_trust("ET-LKG-500")
    time.sleep(1.2)  # let primary expire; LKG TTL is 12x so still alive
    second = await client.get_trust("ET-LKG-500")

    assert first is not None
    assert second is not None
    assert second.band == "good"
    assert second.passport_number == "ET-LKG-500"


@pytest.mark.asyncio
async def test_network_error_serves_lkg_after_prime(monkeypatch):
    _stub_httpx(
        monkeypatch,
        [
            (
                200,
                {
                    "passport_number": "ET-LKG-NET",
                    "status": "active",
                    "band": "fair",
                    "tier_multiplier": 1.0,
                    "cache_ttl_seconds": 300,
                },
            ),
            httpx.ConnectError("refused"),
        ],
    )
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=1, backend=backend
    )
    await client.get_trust("ET-LKG-NET")
    time.sleep(1.2)
    second = await client.get_trust("ET-LKG-NET")
    assert second is not None
    assert second.band == "fair"


@pytest.mark.asyncio
async def test_5xx_without_prime_returns_none(monkeypatch):
    """No prior successful fetch → no LKG → 5xx returns None (not stale)."""
    _stub_httpx(monkeypatch, [(500, None)])
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=1, backend=backend
    )
    assert await client.get_trust("ET-NEW-AND-BROKEN") is None


# ---------------------------------------------------------------------------
# 404 / 429 do NOT fail-soft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_404_does_not_serve_lkg(monkeypatch):
    """Passport explicitly removed from Eternitas — stale-serve would
    be wrong (we'd give the caller access to a deleted bot)."""
    _stub_httpx(
        monkeypatch,
        [
            (
                200,
                {
                    "passport_number": "ET-DELETED",
                    "status": "active",
                    "band": "good",
                    "tier_multiplier": 2.0,
                    "cache_ttl_seconds": 300,
                },
            ),
            (404, None),
        ],
    )
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=1, backend=backend
    )
    await client.get_trust("ET-DELETED")
    time.sleep(1.2)
    # Second fetch: 404. Must return None, NOT the stale LKG.
    result = await client.get_trust("ET-DELETED")
    assert result is None


@pytest.mark.asyncio
async def test_429_does_not_serve_lkg(monkeypatch):
    """Rate-limited — caller's problem to back off; stale-serve would
    obscure the signal."""
    _stub_httpx(
        monkeypatch,
        [
            (
                200,
                {
                    "passport_number": "ET-HAMMERED",
                    "status": "active",
                    "band": "fair",
                    "tier_multiplier": 1.0,
                    "cache_ttl_seconds": 300,
                },
            ),
            (429, None),
        ],
    )
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=1, backend=backend
    )
    await client.get_trust("ET-HAMMERED")
    time.sleep(1.2)
    assert await client.get_trust("ET-HAMMERED") is None


# ---------------------------------------------------------------------------
# invalidate() clears BOTH keyspaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_clears_both_primary_and_lkg(monkeypatch):
    _stub_httpx(
        monkeypatch,
        [
            (
                200,
                {
                    "passport_number": "ET-INV",
                    "status": "active",
                    "band": "good",
                    "tier_multiplier": 2.0,
                    "cache_ttl_seconds": 300,
                },
            ),
        ],
    )
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=300, backend=backend
    )
    await client.get_trust("ET-INV")
    # Both written.
    assert await backend.get(_trust_cache_key("ET-INV")) is not None
    assert await backend.get(_trust_lkg_key("ET-INV")) is not None

    await client.invalidate("ET-INV")
    # Both cleared — a trust.changed webhook means the state is policy-
    # level stale; keeping the LKG would silently serve the old band on
    # the next upstream blip.
    assert await backend.get(_trust_cache_key("ET-INV")) is None
    assert await backend.get(_trust_lkg_key("ET-INV")) is None


# ---------------------------------------------------------------------------
# LKG TTL > primary TTL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lkg_survives_primary_expiry(monkeypatch):
    """The whole point: LKG TTL is 12× primary. After primary expires
    but before LKG does, the LKG is still queryable."""
    _stub_httpx(
        monkeypatch,
        [
            (
                200,
                {
                    "passport_number": "ET-TTL",
                    "status": "active",
                    "band": "good",
                    "tier_multiplier": 2.0,
                    "cache_ttl_seconds": 300,
                },
            ),
        ],
    )
    backend = InMemoryCacheBackend()
    primary_ttl = 1
    client = TrustClient(
        base_url="http://x",
        use_mock=False,
        ttl_seconds=primary_ttl,
        backend=backend,
    )
    await client.get_trust("ET-TTL")
    time.sleep(primary_ttl + 0.2)
    # Primary expired.
    assert await backend.get(_trust_cache_key("ET-TTL")) is None
    # LKG still alive (TTL is primary_ttl * _LKG_MULTIPLIER = 12s).
    assert await backend.get(_trust_lkg_key("ET-TTL")) is not None
    # And the multiplier is the one we documented.
    assert _LKG_MULTIPLIER == 12


# ---------------------------------------------------------------------------
# Corrupt LKG blob
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corrupt_lkg_blob_returns_none_and_deletes(monkeypatch):
    _stub_httpx(monkeypatch, [(500, None)])
    backend = InMemoryCacheBackend()
    # Inject garbage into LKG directly.
    await backend.set(_trust_lkg_key("ET-CORRUPT"), b"not-valid-json{}", 60)
    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=1, backend=backend
    )
    # Primary is empty, LKG is corrupt, HTTP returns 5xx → None.
    result = await client.get_trust("ET-CORRUPT")
    assert result is None
    # Corrupt entry deleted.
    assert await backend.get(_trust_lkg_key("ET-CORRUPT")) is None


# ---------------------------------------------------------------------------
# Primary hit short-circuits — no LKG read / no HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_primary_hit_does_not_touch_http_or_lkg(monkeypatch):
    """Regression guard: if the primary cache is fresh we should not
    attempt HTTP nor fall through to LKG."""
    from api.app.services import trust_client as tc_mod

    class _ExplodeIfCalled:
        def __init__(self, *a, **k):
            raise AssertionError("HTTP must not be touched when primary hits")

    backend = InMemoryCacheBackend()
    info = TrustInfo(
        passport_number="ET-HOT",
        status="active",
        tier_multiplier=2.0,
        band="good",
    )
    await backend.set(_trust_cache_key("ET-HOT"), info.to_bytes(), 300)
    monkeypatch.setattr(tc_mod.httpx, "AsyncClient", _ExplodeIfCalled)

    client = TrustClient(
        base_url="http://x", use_mock=False, ttl_seconds=300, backend=backend
    )
    result = await client.get_trust("ET-HOT")
    assert result is not None
    assert result.band == "good"
