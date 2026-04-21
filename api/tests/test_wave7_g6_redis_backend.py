"""GAP G6: process-local state moved to a shared CacheBackend.

The code must work identically against both backends — in-memory (dev,
empty REDIS_URL) and Redis (prod). These tests exercise the
InMemoryCacheBackend directly for determinism; the RedisCacheBackend
is covered by integration tests that run only when a Redis instance
is reachable.

We assert:
  1. get/set/delete/add_if_new semantics + TTL expiry on the in-memory backend
  2. Factory selects Redis when REDIS_URL is set, in-memory otherwise
  3. TrustClient round-trips a TrustInfo through the cache backend
  4. TrustClient.invalidate actually removes the cached entry
  5. Webhook dedupe via the backend: duplicate delivery-ids are caught
     across simulated "worker instances" by sharing one backend
"""

from __future__ import annotations

import asyncio
import time

import pytest

from api.app.services.cache_backend import (
    InMemoryCacheBackend,
    _reset_cache_backend_for_testing,
    get_cache_backend,
)
from api.app.services.trust_client import (
    TrustClient,
    TrustInfo,
    _reset_trust_client_for_testing,
    _trust_cache_key,
)

# ---------------------------------------------------------------------------
# InMemoryCacheBackend semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inmemory_get_set_delete():
    b = InMemoryCacheBackend()
    assert await b.get("k") is None
    await b.set("k", b"v", 60)
    assert await b.get("k") == b"v"
    await b.delete("k")
    assert await b.get("k") is None


@pytest.mark.asyncio
async def test_inmemory_ttl_expires():
    b = InMemoryCacheBackend()
    await b.set("k", b"v", 1)

    # Simulate expiry by rewinding the stored expiry value instead of sleeping.
    key = next(iter(b._store))
    _old_exp, val = b._store[key]
    b._store[key] = (time.monotonic() - 1, val)

    assert await b.get("k") is None  # expired entries are cleared on read


@pytest.mark.asyncio
async def test_inmemory_add_if_new_is_atomic_across_calls():
    b = InMemoryCacheBackend()
    assert await b.add_if_new("d1", 60) is True
    assert await b.add_if_new("d1", 60) is False  # duplicate
    assert await b.add_if_new("d2", 60) is True


@pytest.mark.asyncio
async def test_inmemory_add_if_new_concurrent():
    """Fire 50 concurrent add_if_new for the same key — exactly one must win."""
    b = InMemoryCacheBackend()
    results = await asyncio.gather(*[b.add_if_new("shared", 60) for _ in range(50)])
    assert sum(1 for r in results if r) == 1


# ---------------------------------------------------------------------------
# Factory selection
# ---------------------------------------------------------------------------


def test_factory_picks_inmemory_when_redis_url_empty(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "redis_url", "")
    _reset_cache_backend_for_testing(None)
    backend = get_cache_backend()
    assert isinstance(backend, InMemoryCacheBackend)
    _reset_cache_backend_for_testing(None)


def test_factory_picks_redis_when_redis_url_set(monkeypatch):
    """Don't actually connect — just assert the right class is instantiated."""
    from api.app.config import settings
    from api.app.services.cache_backend import RedisCacheBackend

    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:65535/0")
    _reset_cache_backend_for_testing(None)
    backend = get_cache_backend()
    assert isinstance(backend, RedisCacheBackend)
    _reset_cache_backend_for_testing(None)


# ---------------------------------------------------------------------------
# TrustClient round-trip through the backend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_client_caches_through_backend():
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://stub",
        use_mock=False,
        backend=backend,
    )

    # Hand-seed a cached entry as if the HTTP call had happened earlier.
    seeded = TrustInfo(
        passport_number="ET-SEED",
        status="active",
        tier_multiplier=2.0,
        band="good",
    )
    await backend.set(_trust_cache_key("ET-SEED"), seeded.to_bytes(), 300)

    got = await client.get_trust("ET-SEED")
    assert got == seeded  # dataclass equality, reconstructed from bytes
    assert got is not seeded  # but it's a new object (came through bytes)


@pytest.mark.asyncio
async def test_trust_client_invalidate_removes_from_backend():
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://stub",
        use_mock=False,
        backend=backend,
    )
    seeded = TrustInfo(
        passport_number="ET-INVAL",
        status="active",
        tier_multiplier=1.0,
    )
    await backend.set(_trust_cache_key("ET-INVAL"), seeded.to_bytes(), 300)

    await client.invalidate("ET-INVAL")
    assert await backend.get(_trust_cache_key("ET-INVAL")) is None


@pytest.mark.asyncio
async def test_corrupt_cache_entry_is_discarded():
    """If the cached bytes aren't parseable, invalidate and return None."""
    backend = InMemoryCacheBackend()
    client = TrustClient(
        base_url="http://stub",
        use_mock=False,
        backend=backend,
    )
    await backend.set(_trust_cache_key("ET-CORRUPT"), b"not json", 300)

    # Can't hit HTTP (bad base_url) — so a None return means we discarded
    # the corrupt entry and then tried + failed the live fetch, which is
    # the right behaviour.
    got = await client.get_trust("ET-CORRUPT")
    assert got is None
    assert await backend.get(_trust_cache_key("ET-CORRUPT")) is None


# ---------------------------------------------------------------------------
# Dedupe across simulated workers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_across_simulated_workers():
    """Two 'workers' sharing one backend dedupe on the same delivery id."""
    shared_backend = InMemoryCacheBackend()
    _reset_cache_backend_for_testing(shared_backend)
    try:
        # Import the dedup helper under the shared backend.
        from api.app.routes.webhooks import _remember_delivery

        # Worker A sees delivery-1 first.
        assert await _remember_delivery("delivery-1") is True
        # Worker B (would be a different Fargate task in prod, same
        # backend because Redis is shared) sees it next — duplicate.
        assert await _remember_delivery("delivery-1") is False

        # Different delivery id is still new.
        assert await _remember_delivery("delivery-2") is True
    finally:
        _reset_cache_backend_for_testing(None)


@pytest.mark.asyncio
async def test_inmemory_backend_does_not_dedup_across_instances():
    """Prove the pre-G6 in-memory-per-worker behaviour — two separate
    InMemoryCacheBackend instances DO NOT share state.

    Without Redis, every Fargate task gets a fresh set of keys. This is
    the exact failure mode G6 fixes by introducing a shared backend.
    """
    worker_a = InMemoryCacheBackend()
    worker_b = InMemoryCacheBackend()

    assert await worker_a.add_if_new("d1", 60) is True
    # Worker B has never seen d1 because its state is separate.
    assert await worker_b.add_if_new("d1", 60) is True


@pytest.fixture(autouse=True)
def _reset_after():
    yield
    _reset_cache_backend_for_testing(None)
    _reset_trust_client_for_testing()
