"""Inbound webhook routes — identity lifecycle and passport revocation.

Wave 2 contracts #1 (identity.created) and #2 (passport.revoked).
"""

from __future__ import annotations

import functools
import json
import logging
from datetime import datetime, timezone
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.jwks import get_eternitas_validator
from api.app.auth.webhook import verify_hmac_sha256
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import IdentityBridge, UserPlan
from api.app.routes.billing import allocate_plan
from api.app.services.trust_client import get_trust_client

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Wave 7 G23 — crash-safe wrapper for webhook handlers.
#
# Eternitas retries webhooks 3 times, then marks the subscriber
# auto-deactivated (docs/webhooks.md §Delivery model). A deterministic
# code bug — say, a DB constraint we forgot to handle — would 500
# three times, then Eternitas stops dispatching to us entirely until an
# operator re-enables the platform. That's a production-outage-shaped
# risk for our own bugs.
#
# This wrapper lets HTTPException propagate (those are intentional
# signaling: bad signature, stale timestamp, missing field), but
# converts any unhandled Python exception into a 200 so Eternitas
# doesn't retry-then-deactivate us. The exception is logged at ERROR
# with full stack + Sentry if configured, so we still see the bug.
# ---------------------------------------------------------------------------

def crash_safe_webhook(fn):
    """Decorator: catch unhandled exceptions, log, return 200.

    Intentional HTTPException (bad signature, stale timestamp, etc.)
    still propagates so the producer sees the error.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except HTTPException:
            # Intentional signaling — let FastAPI render it.
            raise
        except Exception:
            logger.exception(
                "Unhandled exception in webhook handler %s — returning 200 to "
                "avoid producer-side auto-deactivation. FIX THE UNDERLYING BUG.",
                fn.__name__,
            )
            return JSONResponse(
                status_code=200,
                content={"status": "accepted_with_error"},
            )

    return wrapper


# ---------------------------------------------------------------------------
# POST /webhooks/identity/created  (contract #1)
# ---------------------------------------------------------------------------

class IdentityCreatedPayload(BaseModel):
    windy_identity_id: str
    passport_number: str | None = None
    tier: str = "free"
    email: str | None = None
    timestamp: str | None = None

    @classmethod
    def _check_passport(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        from api.app.utils.passport import is_valid_passport_number

        if not is_valid_passport_number(v):
            raise ValueError("Invalid passport_number format")
        return v

    from pydantic import field_validator as _fv

    _pv = _fv("passport_number")(_check_passport)


@router.post("/identity/created", status_code=status.HTTP_201_CREATED)
@crash_safe_webhook
async def handle_identity_created(
    request: Request,
    x_windy_signature: str = Header(..., alias="X-Windy-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Provision a storage plan when Windy Pro creates a new identity.

    HMAC-SHA256 signed body (same pattern as windy-mail's Eternitas webhook).
    Calls allocate_plan internally so the same path is exercised as the
    service-to-service POST /billing/allocate.
    """
    if not settings.identity_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured",
        )
    body_bytes = await request.body()
    if not verify_hmac_sha256(
        body_bytes, x_windy_signature, settings.identity_webhook_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    try:
        payload = IdentityCreatedPayload(**json.loads(body_bytes))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid payload: {exc}",
        ) from exc

    # Link passport first so trust lookups during allocate_plan happen
    # after the bridge row exists (the upload gate consults it later).
    if payload.passport_number:
        await _link_passport(
            db,
            windy_identity_id=payload.windy_identity_id,
            passport_number=payload.passport_number,
            linked_by="webhook.identity.created",
        )

    try:
        plan = await allocate_plan(
            db,
            windy_identity_id=payload.windy_identity_id,
            tier=payload.tier,
            passport_number=payload.passport_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "identity.created allocated tier=%s identity=%s",
        plan.tier,
        plan.identity_id,
    )
    return {
        "status": "provisioned",
        "plan_id": plan.plan_id,
        "quota_bytes": plan.quota_bytes,
        "tier": plan.tier,
    }


# ---------------------------------------------------------------------------
# POST /webhooks/passport/revoked  (contract #2)
# ---------------------------------------------------------------------------

class PassportRevokedPayload(BaseModel):
    """Eternitas revocation payload.

    The signed-JWT form is preferred (`token` field) — the token is signed
    with Eternitas' private key and verifiable via the Eternitas JWKS. A
    signature header on the raw body is accepted as a fallback so older
    senders don't break.
    """
    token: str | None = None
    passport_number: str | None = None
    reason: str | None = None
    event: str | None = None
    timestamp: str | None = None


@router.post("/passport/revoked", status_code=status.HTTP_200_OK)
@crash_safe_webhook
async def handle_passport_revoked(
    payload: PassportRevokedPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Freeze the account tied to a revoked passport.

    Verifies the ES256-signed JWT against Eternitas' JWKS
    (`/.well-known/eternitas-keys`), then marks the matching UserPlan as
    frozen. Upload paths read UserPlan.frozen and reject with 403
    frozen_account.
    """
    if not payload.token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing signed token",
        )

    try:
        validator = get_eternitas_validator()
        claims = validator.validate_token(payload.token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Invalid Eternitas signature: {exc}",
        ) from exc

    passport = (
        claims.get("passport_number")
        or claims.get("passport")
        or claims.get("sub")
        or payload.passport_number
    )
    if not passport:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token missing passport claim",
        )

    bridge_row = await db.execute(
        select(IdentityBridge).where(IdentityBridge.passport_number == passport)
    )
    bridge = bridge_row.scalar_one_or_none()
    if bridge is None:
        logger.warning("passport.revoked: no bridge row for passport=%s", passport)
        return {"status": "unknown_passport", "passport_number": passport}

    plan_row = await db.execute(
        select(UserPlan).where(UserPlan.identity_id == bridge.windy_identity_id)
    )
    plan = plan_row.scalar_one_or_none()
    if plan is None:
        # No plan yet — create a frozen free one so any later upload is blocked
        plan = UserPlan(
            identity_id=bridge.windy_identity_id,
            plan_id="free",
            tier="free",
            quota_bytes=settings.tier_quota_free,
            frozen=True,
        )
        db.add(plan)
    else:
        plan.frozen = True
        plan.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "passport.revoked froze identity=%s passport=%s reason=%s",
        bridge.windy_identity_id,
        passport,
        claims.get("reason") or payload.reason,
    )
    return {
        "status": "frozen",
        "windy_identity_id": bridge.windy_identity_id,
        "passport_number": passport,
    }


# ---------------------------------------------------------------------------
# Shared helper — also used by the identity/link-passport route.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /webhooks/trust/changed  (Wave 4 — cache invalidation)
# ---------------------------------------------------------------------------

class TrustChangedPayload(BaseModel):
    """Eternitas trust.changed envelope — docs/trust-api.md."""

    event: str = "trust.changed"
    event_type: str | None = None
    passport: str | None = None
    passport_number: str | None = None
    reason: str | None = None
    old_band: str | None = None
    new_band: str | None = None
    old_clearance: str | None = None
    new_clearance: str | None = None
    timestamp: str | None = None

    @property
    def resolved_passport(self) -> str:
        return self.passport_number or self.passport or ""


# Best-effort in-memory delivery-id dedupe. A bounded set is enough given
# Eternitas retries 3 times with a 60s max delay — a short-lived cache is fine.
_seen_deliveries: set[str] = set()
_SEEN_MAX = 2048


def _remember_delivery(delivery_id: str) -> bool:
    """Return True if this is a new delivery, False if we've already processed it."""
    if delivery_id in _seen_deliveries:
        return False
    _seen_deliveries.add(delivery_id)
    if len(_seen_deliveries) > _SEEN_MAX:
        # Drop ~half the oldest entries (set is unordered — good enough).
        for d in list(_seen_deliveries)[: _SEEN_MAX // 2]:
            _seen_deliveries.discard(d)
    return True


@router.post("/trust/changed", status_code=status.HTTP_200_OK)
@crash_safe_webhook
async def handle_trust_changed(
    request: Request,
    x_eternitas_signature: str = Header(..., alias="X-Eternitas-Signature"),
    x_eternitas_timestamp: str | None = Header(None, alias="X-Eternitas-Timestamp"),
    x_eternitas_delivery: str | None = Header(None, alias="X-Eternitas-Delivery"),
    x_eternitas_event: str | None = Header(None, alias="X-Eternitas-Event"),
) -> dict[str, Any]:
    """Receive Eternitas trust.changed; flush the local trust cache.

    Signature: X-Eternitas-Signature = "sha256=<hex>" HMAC over the raw body,
    keyed with settings.eternitas_webhook_secret.
    Replay: X-Eternitas-Timestamp older than 5 minutes is rejected.
    Idempotency: dedupe on X-Eternitas-Delivery.
    """
    secret = settings.eternitas_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Eternitas webhook secret not configured",
        )

    # Replay guard
    if x_eternitas_timestamp:
        try:
            ts = int(x_eternitas_timestamp)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Eternitas-Timestamp",
            ) from None
        import time as _time

        if abs(_time.time() - ts) > 300:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stale delivery",
            )

    body_bytes = await request.body()
    if not verify_hmac_sha256(body_bytes, x_eternitas_signature, secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    # Idempotent on delivery id (no-op on duplicate)
    if x_eternitas_delivery and not _remember_delivery(x_eternitas_delivery):
        return {"status": "duplicate", "delivery": x_eternitas_delivery}

    try:
        payload = TrustChangedPayload(**json.loads(body_bytes))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid payload: {exc}",
        ) from exc

    passport = payload.resolved_passport
    if not passport:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing passport in payload",
        )

    get_trust_client().invalidate(passport)
    logger.info(
        "trust.changed invalidated passport=%s reason=%s band=%s→%s clearance=%s→%s",
        passport,
        payload.reason,
        payload.old_band,
        payload.new_band,
        payload.old_clearance,
        payload.new_clearance,
    )
    return {
        "status": "invalidated",
        "passport_number": passport,
    }


# ---------------------------------------------------------------------------
# Shared helper — also used by the identity/link-passport route.
# ---------------------------------------------------------------------------

async def _link_passport(
    db: AsyncSession,
    *,
    windy_identity_id: str,
    passport_number: str,
    operator_email: str | None = None,
    linked_by: str | None = None,
) -> IdentityBridge:
    """Idempotent upsert of a bridge row."""
    result = await db.execute(
        select(IdentityBridge).where(
            IdentityBridge.windy_identity_id == windy_identity_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = IdentityBridge(
            windy_identity_id=windy_identity_id,
            passport_number=passport_number,
            operator_email=operator_email,
            linked_by=linked_by,
        )
        db.add(row)
    else:
        row.passport_number = passport_number
        if operator_email is not None:
            row.operator_email = operator_email
        if linked_by is not None:
            row.linked_by = linked_by
    await db.commit()
    await db.refresh(row)
    return row
