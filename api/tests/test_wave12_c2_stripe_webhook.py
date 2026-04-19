"""Wave 12 C-2 — /api/v1/webhooks/stripe.

Hand-rolled signed payloads (same format Stripe produces with
`stripe listen --forward-to …`). No stripe-cli binary required.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import select

from api.app.config import settings
from api.app.db.models import UserPlan, WebhookDelivery

WEBHOOK_SECRET = "whsec_wave12-test-deterministic"
PRICE_PRO = "price_wave12_pro"
PRICE_ULTRA = "price_wave12_ultra"
PRICE_MAX = "price_wave12_max"


@pytest.fixture(autouse=True)
def configure_stripe(monkeypatch):
    """Every test in this module gets a populated Stripe config."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "stripe_price_id_pro", PRICE_PRO)
    monkeypatch.setattr(settings, "stripe_price_id_ultra", PRICE_ULTRA)
    monkeypatch.setattr(settings, "stripe_price_id_max", PRICE_MAX)
    yield


def _sign(body: bytes, *, secret: str = WEBHOOK_SECRET, ts: int | None = None) -> str:
    if ts is None:
        ts = int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def _subscription_event(
    *,
    event_id: str,
    event_type: str,
    identity_id: str,
    customer_id: str = "cus_wave12_test",
    subscription_id: str = "sub_wave12_test",
    price_id: str = PRICE_PRO,
    status_: str = "active",
) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": subscription_id,
                "customer": customer_id,
                "status": status_,
                "metadata": {"windy_identity_id": identity_id},
                "items": {
                    "data": [{"price": {"id": price_id}}],
                },
            }
        },
    }


def _invoice_event(
    *,
    event_id: str,
    event_type: str,
    customer_id: str = "cus_wave12_test",
) -> dict:
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": {"customer": customer_id}},
    }


# ---------------------------------------------------------------------------
# Signature + replay + malformed headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_header_400(client):
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_missing_secret_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    body = b"{}"
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": _sign(body),
        },
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_tampered_body_rejected(client):
    body = json.dumps({"id": "evt_1", "type": "invoice.payment_succeeded"}).encode()
    sig = _sign(body)
    tampered = body.replace(b"payment_succeeded", b"payment_failed")
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=tampered,
        headers={"Content-Type": "application/json", "Stripe-Signature": sig},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_stale_timestamp_rejected(client):
    body = json.dumps({"id": "evt_stale", "type": "invoice.payment_succeeded"}).encode()
    stale = int(time.time()) - 3600  # 1 hour ago
    sig = _sign(body, ts=stale)
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": sig},
    )
    assert resp.status_code == 400
    assert "stale" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_malformed_signature_header_400(client):
    body = b'{"id":"evt_x","type":"invoice.payment_succeeded"}'
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": "garbled-no-equals",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_event_returns_duplicate(client, db_session):
    event = _invoice_event(event_id="evt_dup_1", event_type="invoice.payment_succeeded")
    # Pre-seed a plan so the handler can find the customer.
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="pro",
            tier="pro",
            quota_bytes=100 * 1024**3,
            stripe_customer_id="cus_wave12_test",
            billing_status="past_due",
        )
    )
    await db_session.commit()

    body = json.dumps(event).encode()
    headers = {"Content-Type": "application/json", "Stripe-Signature": _sign(body)}

    r1 = await client.post("/api/v1/webhooks/stripe", content=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "billing_status=active"

    r2 = await client.post("/api/v1/webhooks/stripe", content=body, headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_ledger_row_persists(client, db_session):
    event = _invoice_event(event_id="evt_ledger_1", event_type="invoice.payment_succeeded")
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="pro",
            tier="pro",
            quota_bytes=100 * 1024**3,
            stripe_customer_id="cus_wave12_test",
        )
    )
    await db_session.commit()

    body = json.dumps(event).encode()
    headers = {"Content-Type": "application/json", "Stripe-Signature": _sign(body)}
    await client.post("/api/v1/webhooks/stripe", content=body, headers=headers)

    row = await db_session.execute(
        select(WebhookDelivery).where(
            WebhookDelivery.provider == "stripe",
            WebhookDelivery.event_id == "evt_ledger_1",
        )
    )
    delivery = row.scalar_one_or_none()
    assert delivery is not None
    assert delivery.event_type == "invoice.payment_succeeded"


# ---------------------------------------------------------------------------
# Event handlers — end-to-end UserPlan mutations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscription_created_sets_tier_and_status(client, db_session):
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="free",
            tier="free",
            quota_bytes=5 * 1024**3,
            billing_status="active",
        )
    )
    await db_session.commit()

    event = _subscription_event(
        event_id="evt_sub_c_1",
        event_type="customer.subscription.created",
        identity_id="test-user-001",
        price_id=PRICE_ULTRA,
        status_="active",
    )
    body = json.dumps(event).encode()
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body)},
    )
    assert resp.status_code == 200, resp.text

    await db_session.commit()
    plan_row = await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "test-user-001")
    )
    plan = plan_row.scalar_one()
    assert plan.tier == "ultra"
    assert plan.billing_status == "active"
    assert plan.stripe_customer_id == "cus_wave12_test"
    assert plan.stripe_subscription_id == "sub_wave12_test"


@pytest.mark.asyncio
async def test_subscription_deleted_downgrades_to_free(client, db_session):
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="ultra",
            tier="ultra",
            quota_bytes=1024**4,
            stripe_customer_id="cus_wave12_test",
            stripe_subscription_id="sub_wave12_test",
            billing_status="active",
        )
    )
    await db_session.commit()

    event = _subscription_event(
        event_id="evt_sub_del_1",
        event_type="customer.subscription.deleted",
        identity_id="test-user-001",
        price_id=PRICE_ULTRA,
        status_="canceled",
    )
    body = json.dumps(event).encode()
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body)},
    )
    assert resp.status_code == 200, resp.text

    await db_session.commit()
    plan_row = await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "test-user-001")
    )
    plan = plan_row.scalar_one()
    assert plan.tier == "free"
    assert plan.billing_status == "canceled"
    assert plan.stripe_subscription_id is None


@pytest.mark.asyncio
async def test_invoice_payment_failed_marks_past_due(client, db_session):
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="pro",
            tier="pro",
            quota_bytes=100 * 1024**3,
            stripe_customer_id="cus_wave12_test",
            billing_status="active",
        )
    )
    await db_session.commit()

    event = _invoice_event(event_id="evt_inv_fail_1", event_type="invoice.payment_failed")
    body = json.dumps(event).encode()
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "billing_status=past_due"


@pytest.mark.asyncio
async def test_unknown_event_type_ignored(client):
    event = {"id": "evt_unknown_1", "type": "charge.refunded"}
    body = json.dumps(event).encode()
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_subscription_missing_metadata_is_ignored(client):
    event = {
        "id": "evt_sub_no_meta",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_no_meta",
                "customer": "cus_unknown",
                "status": "active",
                "metadata": {},
                "items": {"data": [{"price": {"id": PRICE_PRO}}]},
            }
        },
    }
    body = json.dumps(event).encode()
    resp = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored_no_identity"
