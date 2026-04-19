"""Stripe billing webhook.

Wave 12 C-2 — the Wave 9 DEPLOY.md promised this endpoint; it didn't
exist until now (Wave 11 hardening flagged it). Handles subscription
lifecycle + invoice outcomes and mirrors state into UserPlan so
middleware can gate uploads on `billing_status` without round-tripping
Stripe.

Contract:
  - Verify Stripe-Signature (HMAC-SHA256 of `"{t}.{body}"` keyed with
    settings.stripe_webhook_secret). Tolerate multiple `v1=` values
    during secret rotation (Stripe lets you run two secrets for 24 h).
  - Reject deliveries whose timestamp is > 5 min old (replay guard,
    per Stripe's own recommendation).
  - Dedupe on `event.id` via the webhook_deliveries ledger. Duplicate
    replay returns 200 `{"status":"duplicate"}` with no state change.
  - Route five event types. Unknown types 200 with
    `{"status":"ignored"}` so Stripe doesn't retry-then-deactivate us.

Identity resolution:
  - Prefer `subscription.metadata.windy_identity_id`. Callers MUST set
    this at subscription-create time — without it we can't map the
    event to a user and log a warning + 200.
  - Fallback for invoice events: match UserPlan.stripe_customer_id to
    `invoice.customer`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import UserPlan, WebhookDelivery

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

# Stripe rejects deliveries older than 5 min by default; we match that.
MAX_TIMESTAMP_AGE_SECONDS = 300


def _parse_signature_header(header: str) -> tuple[int, list[str]]:
    """Return (timestamp, [v1 signatures...]) parsed from the
    `Stripe-Signature: t=...,v1=...[,v1=...]` header.

    Raises ValueError on malformed input; the caller maps that to 400.
    """
    timestamp: int | None = None
    v1_sigs: list[str] = []
    for part in header.split(","):
        if "=" not in part:
            raise ValueError(f"Malformed sig part: {part!r}")
        k, _, v = part.partition("=")
        k = k.strip()
        v = v.strip()
        if k == "t":
            timestamp = int(v)
        elif k == "v1":
            v1_sigs.append(v)
        # Older `v0` schemes and future versions: ignore silently —
        # Stripe's guidance is to use whichever signature you know.
    if timestamp is None or not v1_sigs:
        raise ValueError("Missing t= or v1= in Stripe-Signature")
    return timestamp, v1_sigs


def _verify_stripe_signature(body: bytes, header: str, secret: str) -> int:
    """Return the timestamp on success; raise HTTPException otherwise.

    The timestamp is returned so the caller can enforce the replay
    window in the same place as the signature check.
    """
    try:
        timestamp, v1_sigs = _parse_signature_header(header)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Stripe-Signature header: {exc}",
        ) from None

    # Replay guard.
    if abs(time.time() - timestamp) > MAX_TIMESTAMP_AGE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stale delivery",
        )

    signed_payload = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

    # hmac.compare_digest over every v1= during rotation windows.
    for sig in v1_sigs:
        if hmac.compare_digest(expected, sig):
            return timestamp

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid signature",
    )


# ---------------------------------------------------------------------------
# Price-id → tier mapping
# ---------------------------------------------------------------------------


def _price_id_to_tier(price_id: str | None) -> str | None:
    """Return "pro" / "ultra" / "max" for a known price, else None.

    Unknown price ids explicitly map to None rather than "free" — we
    don't want to silently downgrade a user because the Stripe catalog
    changed ahead of our env config.
    """
    if not price_id:
        return None
    mapping = {
        settings.stripe_price_id_pro: "pro",
        settings.stripe_price_id_ultra: "ultra",
        settings.stripe_price_id_max: "max",
    }
    mapping.pop("", None)  # Unconfigured env vars map empty-string → drop.
    return mapping.get(price_id)


def _tier_from_subscription(subscription: dict[str, Any]) -> str | None:
    """Pull the first item's price id out of a Stripe subscription and
    resolve to a tier."""
    for item in subscription.get("items", {}).get("data", []) or []:
        price = item.get("price") or {}
        tier = _price_id_to_tier(price.get("id"))
        if tier:
            return tier
    return None


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


async def _record_delivery(db: AsyncSession, *, event_id: str, event_type: str) -> bool:
    """Insert a webhook_deliveries row. Return True on success, False
    if the row already existed (duplicate). Uses the DB's unique
    constraint as the dedupe primitive rather than a pre-select so the
    check is race-free."""
    row = WebhookDelivery(provider="stripe", event_id=event_id, event_type=event_type)
    db.add(row)
    try:
        await db.flush()
        return True
    except IntegrityError:
        await db.rollback()
        return False


# ---------------------------------------------------------------------------
# Per-event handlers
# ---------------------------------------------------------------------------


async def _resolve_plan_for_subscription(
    db: AsyncSession, subscription: dict[str, Any]
) -> UserPlan | None:
    """Try metadata first, fall back to stripe_customer_id match."""
    meta = subscription.get("metadata") or {}
    identity_id = meta.get("windy_identity_id")
    customer_id = subscription.get("customer")

    if identity_id:
        row = await db.execute(select(UserPlan).where(UserPlan.identity_id == identity_id))
        plan = row.scalar_one_or_none()
        if plan is not None:
            return plan

    if customer_id:
        row = await db.execute(select(UserPlan).where(UserPlan.stripe_customer_id == customer_id))
        return row.scalar_one_or_none()

    return None


async def _handle_subscription_created_or_updated(
    db: AsyncSession, event: dict[str, Any]
) -> dict[str, Any]:
    sub = event["data"]["object"]
    plan = await _resolve_plan_for_subscription(db, sub)

    # Creation-time path: if no plan row exists for this identity yet
    # but metadata carries one, create the row rather than silently
    # skipping — the /webhooks/identity/created path may race behind.
    if plan is None:
        meta = sub.get("metadata") or {}
        identity_id = meta.get("windy_identity_id")
        if not identity_id:
            logger.warning(
                "stripe.subscription: missing metadata.windy_identity_id "
                "on event=%s customer=%s — cannot map to a UserPlan. "
                "Clients creating subscriptions MUST set metadata.",
                event.get("id"),
                sub.get("customer"),
            )
            return {"status": "ignored_no_identity"}
        plan = UserPlan(identity_id=identity_id)
        db.add(plan)

    tier = _tier_from_subscription(sub)
    if tier:
        plan.tier = tier
        plan.plan_id = tier
        # Quota stays whatever allocate_plan set last — the dedicated
        # /billing/allocate path is the one source of truth for quota
        # math (it also applies the Eternitas trust multiplier).
    plan.stripe_customer_id = sub.get("customer")
    plan.stripe_subscription_id = sub.get("id")
    plan.billing_status = sub.get("status") or "active"
    await db.commit()
    return {"status": "applied", "tier": plan.tier, "billing_status": plan.billing_status}


async def _handle_subscription_deleted(db: AsyncSession, event: dict[str, Any]) -> dict[str, Any]:
    sub = event["data"]["object"]
    plan = await _resolve_plan_for_subscription(db, sub)
    if plan is None:
        return {"status": "ignored_unknown_plan"}
    plan.tier = "free"
    plan.plan_id = "free"
    plan.billing_status = "canceled"
    plan.stripe_subscription_id = None
    await db.commit()
    return {"status": "downgraded_to_free"}


async def _resolve_plan_for_invoice(db: AsyncSession, invoice: dict[str, Any]) -> UserPlan | None:
    customer_id = invoice.get("customer")
    if not customer_id:
        return None
    row = await db.execute(select(UserPlan).where(UserPlan.stripe_customer_id == customer_id))
    return row.scalar_one_or_none()


async def _handle_invoice_paid(db: AsyncSession, event: dict[str, Any]) -> dict[str, Any]:
    invoice = event["data"]["object"]
    plan = await _resolve_plan_for_invoice(db, invoice)
    if plan is None:
        return {"status": "ignored_unknown_customer"}
    plan.billing_status = "active"
    await db.commit()
    return {"status": "billing_status=active"}


async def _handle_invoice_failed(db: AsyncSession, event: dict[str, Any]) -> dict[str, Any]:
    invoice = event["data"]["object"]
    plan = await _resolve_plan_for_invoice(db, invoice)
    if plan is None:
        return {"status": "ignored_unknown_customer"}
    plan.billing_status = "past_due"
    await db.commit()
    return {"status": "billing_status=past_due"}


_HANDLERS = {
    "customer.subscription.created": _handle_subscription_created_or_updated,
    "customer.subscription.updated": _handle_subscription_created_or_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_succeeded": _handle_invoice_paid,
    "invoice.payment_failed": _handle_invoice_failed,
}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook secret not configured",
        )
    if stripe_signature is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    body = await request.body()
    _verify_stripe_signature(body, stripe_signature, settings.stripe_webhook_secret)

    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {exc}",
        ) from exc

    event_id = event.get("id")
    event_type = event.get("type")
    if not event_id or not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing event id or type",
        )

    # Idempotency — DB unique constraint is the primitive. Flush (not
    # commit) so the ledger row joins the same transaction as the
    # handler mutations: a handler crash rolls back both and Stripe
    # retries cleanly; a handler success commits both atomically.
    recorded = await _record_delivery(db, event_id=event_id, event_type=event_type)
    if not recorded:
        return {"status": "duplicate", "event_id": event_id}

    handler = _HANDLERS.get(event_type)
    if handler is None:
        # Unknown events 200 so Stripe doesn't retry + eventually disable
        # the endpoint. Ledger row commits so we don't re-process on
        # the next identical delivery of an event type we'll never care
        # about.
        logger.info("stripe.event.ignored type=%s id=%s", event_type, event_id)
        await db.commit()
        return {"status": "ignored", "event_type": event_type}

    outcome = await handler(db, event)
    # Handlers commit their own mutations. The ledger row flushed above
    # rode along on that commit; nothing further to do here.
    outcome.setdefault("event_id", event_id)
    return outcome
