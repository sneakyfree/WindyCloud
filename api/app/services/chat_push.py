"""Minimal client for the Windy Chat push-gateway.

Wave 8 — Grandma Ribbon uses this to notify users after the first
auto-backup offer completes ("We just backed up your first N
recordings…"). Only the one call-site exists today; if more
notifications land here we should swap this for a proper queue.

Configuration:
  CHAT_PUSH_GATEWAY_URL   → POST target on Windy Chat side
  CHAT_PUSH_SERVICE_TOKEN → shared secret; sent as X-Service-Token

Unconfigured state is treated as a no-op on purpose: dev + CI
environments rarely have a live Chat instance, and silently failing
there is preferable to 500-ing the offer-backup endpoint. The
production setting is enforced at deploy time via env-var validation,
not at request time.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from api.app.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 3.0


async def send_first_backup_notification(
    *,
    windy_identity_id: str,
    recording_count: int,
    free_gb: int = 5,
) -> bool:
    """Send the grandma-ribbon first-backup notification to Chat.

    Returns True on a 2xx response, False on any failure — the caller
    treats this as best-effort and still marks the offer as processed
    so we don't spam retries on a flaky gateway.
    """
    url = getattr(settings, "chat_push_gateway_url", "") or ""
    token = getattr(settings, "chat_push_service_token", "") or ""
    if not url:
        logger.info(
            "chat_push.gateway_unconfigured identity=%s — skipping notification",
            windy_identity_id,
        )
        return False

    payload: dict[str, Any] = {
        "event": "cloud.first_backup_complete",
        "windy_identity_id": windy_identity_id,
        "recording_count": recording_count,
        "body": (
            f"We just backed up your first {recording_count} recording"
            f"{'s' if recording_count != 1 else ''} to Windy Cloud. "
            f"{free_gb} GB of free storage is yours."
        ),
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Service-Token"] = token

    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning(
            "chat_push.network_error identity=%s err=%s",
            windy_identity_id,
            exc,
        )
        return False

    if resp.status_code >= 400:
        logger.warning(
            "chat_push.bad_status identity=%s status=%s body=%s",
            windy_identity_id,
            resp.status_code,
            resp.text[:200],
        )
        return False

    logger.info(
        "chat_push.sent identity=%s recordings=%s",
        windy_identity_id,
        recording_count,
    )
    return True
