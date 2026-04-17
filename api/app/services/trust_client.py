"""Eternitas Trust API consumer (Wave 3/4).

Fetches per-passport trust data from `GET {eternitas_url}/api/v1/trust/{passport}`
and caches the result in-process for 5 minutes (or whatever `cache_ttl_seconds`
the response suggests, whichever is smaller). When redis lands in windy-cloud
this cache should move there; for now it's process-local — acceptable given
short TTL and the `trust.changed` webhook that invalidates proactively.

Contract reference: /Users/thewindstorm/eternitas/docs/trust-api.md (the
producer-side doc is the single source of truth). The real response is richer
than the stub used in Wave 3 — see `TrustInfo.from_response` for the full
field list.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from api.app.config import settings

logger = logging.getLogger(__name__)


# Band → multiplier projection used server-side. The Trust API already returns
# the effective `tier_multiplier` (LOWER of clearance vs band), so clients
# should prefer the returned value. This table is kept for the fail-open /
# human default path only.
BAND_MULTIPLIERS: dict[str, float] = {
    "exceptional": 5.0,
    "good": 2.0,
    "fair": 1.0,
    "poor": 0.5,
    "critical": 0.0,
}


@dataclass(frozen=True)
class TrustInfo:
    passport_number: str
    status: str                       # "active" | "suspended" | "revoked"
    tier_multiplier: float            # Effective (LOWER of clearance vs band)
    band: str = "fair"                # "exceptional"|"good"|"fair"|"poor"|"critical"
    clearance_level: str = "registered"
    integrity_score: int = 500
    dimensions: dict[str, int] = field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    denied_actions: tuple[str, ...] = ()
    cache_ttl_seconds: int = 300
    evaluated_at: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "TrustInfo":
        band = str(data.get("band") or "fair")
        # Prefer the server-computed multiplier; fall back to band mapping.
        multiplier = data.get("tier_multiplier")
        if multiplier is None:
            multiplier = BAND_MULTIPLIERS.get(band, 1.0)
        return cls(
            passport_number=str(
                data.get("passport_number") or data.get("passport") or ""
            ),
            status=str(data.get("status") or "active"),
            tier_multiplier=float(multiplier),
            band=band,
            clearance_level=str(data.get("clearance_level") or "registered"),
            integrity_score=int(data.get("integrity_score") or 500),
            dimensions=dict(data.get("dimensions") or {}),
            allowed_actions=tuple(data.get("allowed_actions") or ()),
            denied_actions=tuple(data.get("denied_actions") or ()),
            cache_ttl_seconds=int(data.get("cache_ttl_seconds") or 300),
            evaluated_at=str(data.get("evaluated_at") or ""),
        )

    @classmethod
    def default_for_human(cls) -> "TrustInfo":
        """Humans have no passport — treat as active, fair-band, 1.0 multiplier."""
        return cls(
            passport_number="",
            status="active",
            tier_multiplier=1.0,
            band="fair",
            clearance_level="verified",
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TrustClient:
    """Async Eternitas Trust API client with in-memory TTL cache."""

    def __init__(
        self,
        base_url: str | None = None,
        ttl_seconds: int | None = None,
        timeout: float | None = None,
        use_mock: bool | None = None,
    ):
        self._base_url = (base_url or settings.eternitas_url).rstrip("/")
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.trust_cache_ttl_seconds
        self._timeout = timeout if timeout is not None else settings.trust_http_timeout_seconds
        self._use_mock = bool(
            use_mock if use_mock is not None else settings.eternitas_use_mock
        )
        self._cache: dict[str, tuple[float, TrustInfo]] = {}
        self._lock = asyncio.Lock()

    async def get_trust(self, passport_number: str) -> TrustInfo | None:
        """Return trust info for `passport_number`, or None if unknown.

        Behavior:
        - ETERNITAS_USE_MOCK=true → always returns None (unit tests swap in a stub).
        - Unknown passport at upstream → 404 → returns None (not cached).
        - Network / 5xx error → returns last cached value if any, else None (logged).
        - Otherwise caches for min(ttl, response.cache_ttl_seconds).
        """
        if not passport_number:
            return None
        if self._use_mock:
            return None

        now = time.monotonic()
        cached = self._cache.get(passport_number)
        if cached and (now - cached[0]) < self._ttl:
            return cached[1]

        # Defense in depth for GAP G21: validate-on-ingress is the primary
        # guard, but if a malformed passport somehow reaches here we
        # percent-encode it so it can only ever be interpreted as a
        # single path segment, never as /../ or /?query.
        url = f"{self._base_url}/api/v1/trust/{quote(passport_number, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Trust lookup failed for %s: %s", passport_number, exc)
            if cached:
                return cached[1]
            return None

        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            logger.warning("Trust API rate-limited on %s", passport_number)
            if cached:
                return cached[1]
            return None
        if resp.status_code != 200:
            logger.warning(
                "Trust lookup for %s returned %s: %s",
                passport_number,
                resp.status_code,
                resp.text[:200],
            )
            if cached:
                return cached[1]
            return None

        info = TrustInfo.from_response(resp.json())
        # Store no longer than the server hint suggests.
        effective_ttl = min(self._ttl, info.cache_ttl_seconds or self._ttl)
        async with self._lock:
            self._cache[passport_number] = (now - (self._ttl - effective_ttl), info)
        return info

    def invalidate(self, passport_number: str) -> None:
        """Drop the cached entry for a passport — call from trust.changed webhook."""
        self._cache.pop(passport_number, None)

    def clear_cache(self) -> None:
        self._cache.clear()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_trust_client: TrustClient | None = None


def get_trust_client() -> TrustClient:
    global _trust_client
    if _trust_client is None:
        _trust_client = TrustClient()
    return _trust_client


def _reset_trust_client_for_testing() -> None:
    """Tests may swap the singleton — use this to avoid leaking state."""
    global _trust_client
    _trust_client = None
