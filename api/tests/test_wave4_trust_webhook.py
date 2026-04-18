"""Wave 4 — trust.changed webhook receiver (offline unit tests).

These don't need a running Eternitas; they exercise the handler on our side:
signature verification, replay protection, idempotency, cache invalidation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from api.app.config import settings
from api.app.services.trust_client import TrustInfo, get_trust_client

WEBHOOK_SECRET = "wave4-trust-secret"


@pytest.fixture
def trust_secret(monkeypatch):
    monkeypatch.setattr(settings, "eternitas_webhook_secret", WEBHOOK_SECRET)
    # Also reset the dedupe set between tests so timestamps don't collide.
    from api.app.routes import webhooks as wh

    wh._seen_deliveries.clear()
    return WEBHOOK_SECRET


def _signed_delivery(payload: dict, secret: str = WEBHOOK_SECRET) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-Eternitas-Signature": sig,
        "X-Eternitas-Event": "trust.changed",
        "X-Eternitas-Timestamp": str(int(time.time())),
        "X-Eternitas-Delivery": f"d-{time.time_ns()}",
        "Content-Type": "application/json",
    }
    return body, headers


@pytest.mark.asyncio
async def test_flushes_cache_on_valid_delivery(client, trust_secret):
    cl = get_trust_client()
    cl._cache["ET-FLUSH"] = (
        time.monotonic(),
        TrustInfo(passport_number="ET-FLUSH", status="active", tier_multiplier=1.0),
    )

    body, headers = _signed_delivery({
        "event": "trust.changed",
        "passport_number": "ET-FLUSH",
        "reason": "integrity_band: good→fair",
        "old_band": "good",
        "new_band": "fair",
    })
    resp = await client.post(
        "/api/v1/webhooks/trust/changed", content=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "invalidated"
    assert "ET-FLUSH" not in cl._cache


@pytest.mark.asyncio
async def test_rejects_bad_signature(client, trust_secret):
    body, headers = _signed_delivery({
        "event": "trust.changed",
        "passport_number": "ET-BAD",
    })
    headers["X-Eternitas-Signature"] = "sha256=deadbeef"
    resp = await client.post(
        "/api/v1/webhooks/trust/changed", content=body, headers=headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rejects_stale_timestamp(client, trust_secret):
    body, headers = _signed_delivery({
        "event": "trust.changed",
        "passport_number": "ET-OLD",
    })
    headers["X-Eternitas-Timestamp"] = str(int(time.time()) - 600)  # 10 min old
    resp = await client.post(
        "/api/v1/webhooks/trust/changed", content=body, headers=headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_dedupes_delivery_id(client, trust_secret):
    body, headers = _signed_delivery({
        "event": "trust.changed",
        "passport_number": "ET-DEDUPE",
    })
    # Freeze the delivery id so both posts look identical
    headers["X-Eternitas-Delivery"] = "stable-id-xyz"

    r1 = await client.post(
        "/api/v1/webhooks/trust/changed", content=body, headers=headers
    )
    r2 = await client.post(
        "/api/v1/webhooks/trust/changed", content=body, headers=headers
    )
    assert r1.status_code == 200 and r1.json()["status"] == "invalidated"
    assert r2.status_code == 200 and r2.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_503_when_secret_unset(client):
    # No trust_secret fixture → settings.eternitas_webhook_secret is "".
    body = json.dumps({"event": "trust.changed", "passport_number": "ET-X"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/trust/changed",
        content=body,
        headers={
            "X-Eternitas-Signature": "sha256=whatever",
            "X-Eternitas-Timestamp": str(int(time.time())),
        },
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_use_mock_flag_skips_http(monkeypatch):
    """With ETERNITAS_USE_MOCK=true, TrustClient returns None without hitting HTTP."""
    from api.app.services.trust_client import TrustClient

    c = TrustClient(base_url="http://127.0.0.1:1", use_mock=True, timeout=0.5)
    info = await c.get_trust("ET-WHATEVER")
    assert info is None  # no network call attempted
