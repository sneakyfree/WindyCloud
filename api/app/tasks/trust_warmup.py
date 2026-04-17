"""Trust cache warmup (Wave 7 G22).

On rolling deploy, every new Fargate task starts with an empty trust
cache. The first upload-gate call per-passport hits Eternitas
synchronously — so a deploy correlates with a burst of synchronous
Trust API calls, which:
  - adds per-request latency
  - pressures Eternitas's 100/min/IP rate limit
  - with G8's fail-closed write gate, turns trust timeouts into 503s
    for the first few writes per identity

This task runs once at app lifespan startup: reads the passport list
out of the identity bridge, and fetches trust for each one in a
rate-limited background trickle. Failures are logged and skipped —
the worker serves traffic regardless of whether warmup succeeds.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.db.models import IdentityBridge

logger = logging.getLogger(__name__)

# Pace the warmup so we don't hammer Eternitas's 100/min/IP limit —
# 20/sec gives plenty of headroom for normal traffic alongside.
_WARMUP_INTERVAL_SECONDS = 0.05  # 20 per second
_WARMUP_MAX_PASSPORTS = 500  # hard cap so startup doesn't block on huge tables


async def warmup_trust_cache(
    db: AsyncSession,
    *,
    interval: float = _WARMUP_INTERVAL_SECONDS,
    max_passports: int = _WARMUP_MAX_PASSPORTS,
) -> dict[str, int]:
    """Pre-fetch Trust API data for every linked passport.

    Returns a counter dict for metrics / logs: {"attempted", "ok", "failed"}.
    """
    from api.app.services.trust_client import get_trust_client

    result = await db.execute(
        select(IdentityBridge.passport_number).limit(max_passports)
    )
    passports = [row[0] for row in result.all()]

    if not passports:
        logger.info("trust-warmup: bridge table empty, skipping")
        return {"attempted": 0, "ok": 0, "failed": 0}

    client = get_trust_client()
    ok = 0
    failed = 0
    for passport in passports:
        try:
            info = await client.get_trust(passport)
            if info is not None:
                ok += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("trust-warmup: fetch failed for %s: %s", passport, exc)
            failed += 1
        await asyncio.sleep(interval)

    counters = {
        "attempted": len(passports),
        "ok": ok,
        "failed": failed,
    }
    logger.info(
        "trust-warmup: pre-fetched %(ok)d/%(attempted)d passports "
        "(failed=%(failed)d)",
        counters,
    )
    return counters
