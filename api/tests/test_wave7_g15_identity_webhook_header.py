"""GAP G15: identity/created uses X-Pro-Signature + X-Pro-Timestamp.

The header was `X-Windy-Signature` pre-G15 — an accidental collision
with Eternitas's reservation of that name for detached ES256 JWS. If
Pro ever adopted the ecosystem signing scheme, Cloud would still have
interpreted the header as HMAC and silently 403'd.

This test suite pins:
  - X-Pro-Signature is the new canonical header
  - X-Pro-Timestamp enforces replay freshness (< 5 min)
  - X-Windy-Signature is still accepted (deprecation window)
  - New-header callers without a timestamp are rejected
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

WEBHOOK_SECRET = "g15-webhook-secret"


@pytest.fixture
def hmac_secret(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "identity_webhook_secret", WEBHOOK_SECRET)
    return WEBHOOK_SECRET


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_new_header_with_fresh_timestamp_accepted(client, hmac_secret):
    body = json.dumps({"windy_identity_id": "g15-new-1", "tier": "free"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Pro-Signature": _sign(body),
            "X-Pro-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_new_header_with_stale_timestamp_rejected(client, hmac_secret):
    """Timestamp older than 5 min must reject — prevents replay of
    a captured (signature, body) pair."""
    body = json.dumps({"windy_identity_id": "g15-stale-1", "tier": "free"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Pro-Signature": _sign(body),
            "X-Pro-Timestamp": str(int(time.time()) - 600),  # 10 min old
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400
    assert "stale" in resp.text.lower() or "timestamp" in resp.text.lower()


@pytest.mark.asyncio
async def test_new_header_without_timestamp_rejected(client, hmac_secret):
    body = json.dumps({"windy_identity_id": "g15-nots-1", "tier": "free"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Pro-Signature": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400
    assert "timestamp" in resp.text.lower()


@pytest.mark.asyncio
async def test_legacy_header_still_accepted(client, hmac_secret):
    """During the deprecation window, X-Windy-Signature must still work
    without a timestamp so windy-pro can migrate on its own cadence."""
    body = json.dumps({"windy_identity_id": "g15-legacy-1", "tier": "free"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Windy-Signature": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_bad_signature_rejected_both_headers(client, hmac_secret):
    body = json.dumps({"windy_identity_id": "g15-bad-1", "tier": "free"}).encode()

    # New header, bad sig
    r1 = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Pro-Signature": "deadbeef",
            "X-Pro-Timestamp": str(int(time.time())),
        },
    )
    assert r1.status_code == 403

    # Legacy header, bad sig
    r2 = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={"X-Windy-Signature": "deadbeef"},
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_no_signature_header_rejected(client, hmac_secret):
    body = json.dumps({"windy_identity_id": "g15-nos-1", "tier": "free"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_new_header_takes_precedence_over_legacy(client, hmac_secret):
    """If both headers are present, the new one wins. A bad legacy sig
    doesn't matter if the new header is valid."""
    body = json.dumps({"windy_identity_id": "g15-both-1", "tier": "free"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Pro-Signature": _sign(body),
            "X-Pro-Timestamp": str(int(time.time())),
            "X-Windy-Signature": "deadbeef",  # wrong, but ignored
        },
    )
    assert resp.status_code == 201
