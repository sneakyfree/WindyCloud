"""Fire-and-forget event emission to Windy Admin (ADR-WA-001).

Telemetry must NEVER affect product traffic: posts run as background
tasks with a short timeout, every error is swallowed (debug-logged),
and the module is inert unless both WINDY_ADMIN_INGEST_URL and
WINDY_ADMIN_INGEST_TOKEN are configured.

Privacy hard line (ADR-WA-001 §4): envelopes carry counts, sizes,
durations, products, and ids only — never file content or names that
could embed content. The ingest rejects content-like metadata keys with
422; keep it that way by fixing the emitter, not the guard.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from api.app.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
# Strong refs so fire-and-forget tasks aren't garbage-collected mid-flight.
_inflight: set[asyncio.Task] = set()


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=2.0)
    return _client


async def _send(events: list[dict]) -> None:
    try:
        resp = await _get_client().post(
            f"{settings.windy_admin_ingest_url.rstrip('/')}/v1/events",
            json={"events": events},
            headers={"Authorization": f"Bearer {settings.windy_admin_ingest_token}"},
        )
        if resp.status_code != 202:
            logger.debug("telemetry ingest returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:  # noqa: BLE001 — telemetry never raises
        logger.debug("telemetry post failed: %s", e)


def emit(
    event_type: str,
    *,
    actor_type: str = "agent",
    actor_id: str | None = None,
    duration_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Queue one envelope for delivery; a no-op unless configured.

    Content-free by construction: only pass counts/sizes/ids/products in
    ``metadata`` — never filenames, message bodies, or transcripts.
    """
    if not (settings.windy_admin_ingest_url and settings.windy_admin_ingest_token):
        return
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "platform": "windy-cloud",
        "service": "windy-cloud-api",
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "duration_ms": duration_ms,
        "metadata": metadata or {},
    }
    try:
        task = asyncio.get_running_loop().create_task(_send([event]))
    except RuntimeError:
        return  # no running loop (sync context) — drop rather than block
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)
