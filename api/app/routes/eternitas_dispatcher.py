"""Wave 14 P0 — unified `/webhooks/eternitas` dispatcher.

Eternitas registers **one** webhook URL per subscriber and fans every
event type to it, tagging the event class on the `X-Eternitas-Event`
header (with `event` / `event_type` in the body as a secondary signal).

Pre-Wave-14, Cloud only exposed the three event-specific canonical
endpoints under `/api/v1/webhooks/`:

  - POST /api/v1/webhooks/trust/changed
  - POST /api/v1/webhooks/passport/revoked
  - POST /api/v1/webhooks/passport/reinstated

Eternitas's `platforms.windycloud.webhook_url` in the registry is
`https://cloud.windyword.ai/webhooks/eternitas` (no `/api/v1` prefix,
unified path). Every event posted there 404-ed — the 2026-04-20 00:09 UTC
fanout logged `HTTP 404` / `dead_letter` against `plt_f01…` in
Eternitas's `webhook_deliveries` table. Passport revocations + trust-
cache invalidations silently dropped.

This module restores delivery by mounting one no-prefix handler that
inspects `X-Eternitas-Event` and re-dispatches to the existing Wave-4/7/
12 endpoint logic. The canonical per-event routes under `/api/v1/
webhooks/` remain untouched so direct callers (tests, internal tooling,
future subscribers) still work the old way.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.db.engine import get_db
from api.app.routes.webhooks import (
    PassportReinstatedPayload,
    PassportRevokedPayload,
    handle_passport_reinstated,
    handle_passport_revoked,
    handle_trust_changed,
)

logger = logging.getLogger(__name__)
router = APIRouter()


_HMAC_EVENTS = {"trust.changed"}
_SIGNED_JWT_EVENTS = {"passport.revoked", "passport.reinstated"}


async def _resolve_event_type(
    header_value: str | None, raw_body: bytes
) -> tuple[str, dict[str, Any] | None]:
    """Pick the event type from header first, falling back to the body.

    Returns `(event_type, parsed_body_or_None)`. Parsed body is cached
    and returned so the caller doesn't re-decode a known-bad JSON blob.
    """
    event_type = (header_value or "").strip().lower()
    body_json: dict[str, Any] | None = None
    if not event_type and raw_body:
        try:
            decoded = json.loads(raw_body)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            body_json = decoded
            event_type = (decoded.get("event") or decoded.get("event_type") or "").strip().lower()
    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Eternitas-Event header and no `event` field in body",
        )
    return event_type, body_json


@router.post("/webhooks/eternitas")
async def dispatch_eternitas(
    request: Request,
    x_eternitas_event: str | None = Header(None, alias="X-Eternitas-Event"),
    x_eternitas_signature: str | None = Header(None, alias="X-Eternitas-Signature"),
    x_eternitas_timestamp: str | None = Header(None, alias="X-Eternitas-Timestamp"),
    x_eternitas_delivery: str | None = Header(None, alias="X-Eternitas-Delivery"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Route an Eternitas fanout event to the right Wave-4/7/12 handler.

    Starlette caches the request body on first read, so the downstream
    handler's own `await request.body()` gets the same bytes we just
    inspected — HMAC verification proceeds unchanged.
    """
    raw_body = await request.body()
    event_type, body_json = await _resolve_event_type(x_eternitas_event, raw_body)

    if event_type in _HMAC_EVENTS:
        if not x_eternitas_signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{event_type} requires X-Eternitas-Signature",
            )
        return await handle_trust_changed(
            request=request,
            x_eternitas_signature=x_eternitas_signature,
            x_eternitas_timestamp=x_eternitas_timestamp,
            x_eternitas_delivery=x_eternitas_delivery,
            x_eternitas_event=x_eternitas_event,
        )

    if event_type in _SIGNED_JWT_EVENTS:
        if body_json is None:
            try:
                body_json = json.loads(raw_body) if raw_body else None
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid JSON body: {exc}",
                ) from exc
        if not isinstance(body_json, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Body must be a JSON object",
            )
        if event_type == "passport.revoked":
            return await handle_passport_revoked(payload=PassportRevokedPayload(**body_json), db=db)
        return await handle_passport_reinstated(
            payload=PassportReinstatedPayload(**body_json), db=db
        )

    # Unknown event class. Mirror the Stripe-webhook convention: return
    # 200 with `status:"ignored"` so Eternitas doesn't retry-then-auto-
    # deactivate us on a benign event we simply don't consume (e.g. a
    # future `passport.renewed`).
    logger.warning("Dispatcher received unknown Eternitas event: %s", event_type)
    return {"status": "ignored", "event_type": event_type}
