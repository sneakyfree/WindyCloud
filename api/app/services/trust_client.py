"""Eternitas Trust API consumer (Wave 3/4/7).

Fetches per-passport trust data from `GET {eternitas_url}/api/v1/trust/{passport}`
and caches the result through a shared `CacheBackend` (Redis in prod,
in-memory fallback for dev/tests — see `services/cache_backend.py`).

Wave 7 G6: prior in-process dict meant one `trust.changed` webhook only
invalidated the worker that received it; other Fargate tasks kept
serving stale trust until TTL. Redis gives us one authoritative cache
the whole fleet reads and writes through; the local `invalidate()`
call on webhook receipt now flushes for every worker at once.

Contract reference: /Users/thewindstorm/eternitas/docs/trust-api.md.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from api.app.config import settings
from api.app.services.cache_backend import CacheBackend, get_cache_backend

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
    status: str  # "active" | "suspended" | "revoked"
    tier_multiplier: float  # Effective (LOWER of clearance vs band)
    band: str = "fair"  # "exceptional"|"good"|"fair"|"poor"|"critical"
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

    def to_bytes(self) -> bytes:
        d = asdict(self)
        # allowed/denied_actions are tuples in-memory; JSON doesn't care but
        # asdict leaves them as tuples → JSON serialises them as lists fine.
        return json.dumps(d, separators=(",", ":")).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "TrustInfo":
        d = json.loads(raw)
        d["allowed_actions"] = tuple(d.get("allowed_actions") or ())
        d["denied_actions"] = tuple(d.get("denied_actions") or ())
        d["dimensions"] = dict(d.get("dimensions") or {})
        return cls(**d)

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "TrustInfo":
        band = str(data.get("band") or "fair")
        # Prefer the server-computed multiplier; fall back to band mapping.
        multiplier = data.get("tier_multiplier")
        if multiplier is None:
            multiplier = BAND_MULTIPLIERS.get(band, 1.0)
        return cls(
            passport_number=str(data.get("passport_number") or data.get("passport") or ""),
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

def _trust_cache_key(passport_number: str) -> str:
    return f"trust:{passport_number}"


def _trust_lkg_key(passport_number: str) -> str:
    """Last-known-good key — a longer-TTL shadow of the primary cache.

    Pre-G6 the in-process dict served the stale entry when an upstream
    refresh 5xx'd, so a flaky Eternitas didn't black-hole trust lookups.
    G6 moved caching to Redis; Redis strictly honours TTLs and the
    stale-on-5xx fail-soft went with it. Wave 14 restores that semantic
    via this second keyspace — when the primary expires and the refresh
    fetch fails, we fall back here. Successful fetches write to both;
    `invalidate()` clears both (a trust.changed webhook means the
    user's trust state changed for a policy reason, so even the LKG
    is now wrong).
    """
    return f"trust:lkg:{passport_number}"


# LKG TTL is a multiple of the primary cache TTL. Long enough to
# survive a real Eternitas outage (typical multi-minute blip); short
# enough that a stale trust tier can't linger for days after an
# operator forgets to flush.
_LKG_MULTIPLIER = 12


class TrustClient:
    """Async Eternitas Trust API client fronted by a shared CacheBackend."""

    def __init__(
        self,
        base_url: str | None = None,
        ttl_seconds: int | None = None,
        timeout: float | None = None,
        use_mock: bool | None = None,
        backend: CacheBackend | None = None,
    ):
        self._base_url = (base_url or settings.eternitas_url).rstrip("/")
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.trust_cache_ttl_seconds
        self._timeout = timeout if timeout is not None else settings.trust_http_timeout_seconds
        self._use_mock = bool(
            use_mock if use_mock is not None else settings.eternitas_use_mock
        )
        self._backend = backend or get_cache_backend()

    async def get_trust(self, passport_number: str) -> TrustInfo | None:
        """Return trust info for `passport_number`, or None if unknown.

        Lookup order:
          1. Primary cache (CacheBackend). Hit → return.
          2. Live HTTP to Eternitas.
          3. On 5xx / network error: last-known-good keyspace.
             If an LKG exists, serve + log a warning. If not, return None.
          4. 404 / 429 are NOT fail-soft: 404 means the passport was
             explicitly removed (stale-serve would be wrong); 429 is the
             caller's problem to back off — serving stale would obscure
             the rate-limit signal.

        Successful fetches write to BOTH keyspaces.
        `invalidate()` clears BOTH keyspaces.
        """
        if not passport_number or self._use_mock:
            return None

        key = _trust_cache_key(passport_number)
        lkg_key = _trust_lkg_key(passport_number)

        cached = await self._backend.get(key)
        if cached is not None:
            try:
                return TrustInfo.from_bytes(cached)
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                logger.warning("Corrupt trust cache for %s: %s", passport_number, exc)
                await self._backend.delete(key)

        # Defense in depth for GAP G21: validate-on-ingress is the primary
        # guard, but if a malformed passport somehow reaches here we
        # percent-encode it so it can only ever be interpreted as a
        # single path segment, never as /../ or /?query.
        url = f"{self._base_url}/api/v1/trust/{quote(passport_number, safe='')}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Trust lookup failed for %s: %s — falling back to LKG",
                passport_number, exc,
            )
            return await self._serve_lkg(lkg_key, passport_number)

        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            logger.warning("Trust API rate-limited on %s", passport_number)
            return None
        if resp.status_code >= 500:
            logger.warning(
                "Trust lookup for %s returned %s — falling back to LKG",
                passport_number, resp.status_code,
            )
            return await self._serve_lkg(lkg_key, passport_number)
        if resp.status_code != 200:
            logger.warning(
                "Trust lookup for %s returned %s: %s",
                passport_number,
                resp.status_code,
                resp.text[:200],
            )
            return None

        info = TrustInfo.from_response(resp.json())
        effective_ttl = min(self._ttl, info.cache_ttl_seconds or self._ttl)
        if effective_ttl > 0:
            # Write primary + LKG atomically-enough — if one write fails
            # (Redis outage mid-request), the backend logs and moves on.
            # Worst case: primary hit, LKG miss → next refresh on 5xx
            # returns None instead of the prior stale value. That's the
            # pre-Wave-14 degraded mode; no regression.
            payload = info.to_bytes()
            await self._backend.set(key, payload, effective_ttl)
            await self._backend.set(lkg_key, payload, effective_ttl * _LKG_MULTIPLIER)
        return info

    async def _serve_lkg(
        self, lkg_key: str, passport_number: str
    ) -> TrustInfo | None:
        """Return the last-known-good entry if present, else None."""
        raw = await self._backend.get(lkg_key)
        if raw is None:
            return None
        try:
            info = TrustInfo.from_bytes(raw)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Corrupt LKG trust cache for %s: %s", passport_number, exc)
            await self._backend.delete(lkg_key)
            return None
        logger.info(
            "Trust fail-soft: serving stale LKG for %s (band=%s status=%s)",
            passport_number, info.band, info.status,
        )
        return info

    async def invalidate(self, passport_number: str) -> None:
        """Drop BOTH cached entries — call from the trust.changed webhook.

        A trust.changed event means the user's state changed for a policy
        reason (band downgrade, suspension, clearance revocation).
        Keeping the LKG in place would silently serve the old band on the
        next upstream blip — that's the exact failure mode webhooks
        exist to prevent. Flushing both keyspaces for every worker at
        once is the whole reason G6 moved to Redis in the first place.
        """
        await self._backend.delete(_trust_cache_key(passport_number))
        await self._backend.delete(_trust_lkg_key(passport_number))

    async def clear_cache(self) -> None:
        # Rarely needed — used in tests.
        await self._backend.aclose()


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
