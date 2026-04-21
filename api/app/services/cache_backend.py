"""Cache / dedup backend abstraction.

Wave 7 G6 fix. Two process-local data bags broke silently across
horizontally-scaled Fargate workers:

  - `TrustClient._cache` — per-worker trust lookups, so a `trust.changed`
    webhook only invalidated the cache on the worker that received it.
    Other workers served stale trust until their 5-min TTL rolled over.
  - `webhooks._seen_deliveries` — per-worker delivery-id dedupe, so
    Eternitas retries could land on different workers and re-process.

Both are now fronted by a `CacheBackend` that's backed by Redis when
`REDIS_URL` is set, and an in-memory dict otherwise. The in-memory
version matches the old semantics exactly for single-worker dev / tests.

This module intentionally does NOT own the upload-concurrency
semaphore in archive.py / storage.py. A distributed concurrency limit
over Redis is expensive per-request (every upload takes a round-trip
lock) and the better control point is edge rate-limiting plus a
sensible per-worker `asyncio.Semaphore`. Those are tuned in-place.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

logger = logging.getLogger(__name__)


class CacheBackend(Protocol):
    """Thin interface both Redis and in-memory implementations satisfy."""

    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def add_if_new(self, key: str, ttl_seconds: int) -> bool:
        """Atomically add `key` if absent; return True if we added it
        (first time seen), False if it already existed (duplicate)."""
        ...

    async def aclose(self) -> None: ...


# ---------------------------------------------------------------------------
# In-memory backend — the pre-G6 behaviour.
# ---------------------------------------------------------------------------


class InMemoryCacheBackend:
    """Process-local dict with per-key expiry. Safe single-threaded-asyncio."""

    def __init__(self):
        self._store: dict[str, tuple[float, bytes]] = {}

    def _expired(self, expiry: float) -> bool:
        return expiry <= time.monotonic()

    async def get(self, key: str) -> bytes | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if self._expired(expiry):
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def add_if_new(self, key: str, ttl_seconds: int) -> bool:
        entry = self._store.get(key)
        if entry is not None and not self._expired(entry[0]):
            return False
        self._store[key] = (time.monotonic() + ttl_seconds, b"1")
        return True

    async def aclose(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Redis backend — used when REDIS_URL is set.
# ---------------------------------------------------------------------------


class RedisCacheBackend:
    """Redis-backed cache/dedup. All operations go through one async pool.

    Fails soft: connection / command errors propagate as None (get) or
    False (add_if_new) so a Redis outage degrades to "nothing cached,
    nothing deduped" instead of breaking the request path.
    """

    def __init__(self, url: str, key_prefix: str = "windycloud"):
        # Import lazily so the test suite doesn't need redis installed
        # when REDIS_URL is unset.
        from redis import asyncio as aioredis

        self._client = aioredis.from_url(
            url,
            encoding=None,
            decode_responses=False,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        self._prefix = key_prefix

    def _k(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> bytes | None:
        try:
            return await self._client.get(self._k(key))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis GET %s failed: %s", key, exc)
            return None

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        try:
            await self._client.set(self._k(key), value, ex=ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis SET %s failed: %s", key, exc)

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(self._k(key))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis DEL %s failed: %s", key, exc)

    async def add_if_new(self, key: str, ttl_seconds: int) -> bool:
        try:
            # SET NX + EX in one command — atomic add-if-absent with TTL.
            result = await self._client.set(self._k(key), b"1", nx=True, ex=ttl_seconds)
            return bool(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis SETNX %s failed: %s", key, exc)
            # Safe default on Redis outage: treat as NEW. That means a
            # retry might double-process, but idempotent handlers cope —
            # and we don't want a flaky Redis to silently black-hole
            # every webhook.
            return True

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Singleton + factory
# ---------------------------------------------------------------------------

_backend: CacheBackend | None = None


def get_cache_backend() -> CacheBackend:
    """Return the process-wide backend — Redis if REDIS_URL is set, else in-memory."""
    global _backend
    if _backend is not None:
        return _backend
    from api.app.config import settings

    if settings.redis_url:
        _backend = RedisCacheBackend(settings.redis_url)
        logger.info("Cache backend: Redis at %s", settings.redis_url)
    else:
        _backend = InMemoryCacheBackend()
        logger.info("Cache backend: in-memory (REDIS_URL unset)")
    return _backend


def _reset_cache_backend_for_testing(backend: CacheBackend | None = None) -> None:
    """Tests can swap in a custom backend or reset to rebuild on next call."""
    global _backend
    _backend = backend
