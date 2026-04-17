"""Tests for identity.created + passport.revoked webhooks (Wave 2 #1, #2)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from api.app.db.models import IdentityBridge, UserPlan

WEBHOOK_SECRET = "test-hmac-secret-v1"


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def hmac_secret(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "identity_webhook_secret", WEBHOOK_SECRET)
    return WEBHOOK_SECRET


@pytest.fixture
def eternitas_es256(monkeypatch):
    """Patch get_eternitas_validator to accept tokens signed by a local ES256 key."""
    from api.app.auth import jwks as jwks_mod
    from api.app.routes import webhooks as webhooks_mod

    private_key = ec.generate_private_key(ec.SECP256R1())
    pem_priv = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pem_pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    class _StubValidator:
        def validate_token(self, token: str):
            return pyjwt.decode(token, pem_pub, algorithms=["ES256"])

    stub = _StubValidator()
    monkeypatch.setattr(jwks_mod, "_eternitas_validator", stub)
    monkeypatch.setattr(jwks_mod, "get_eternitas_validator", lambda: stub)
    monkeypatch.setattr(webhooks_mod, "get_eternitas_validator", lambda: stub)

    def _sign_token(claims: dict) -> str:
        return pyjwt.encode(claims, pem_priv, algorithm="ES256")

    return _sign_token


# ---------------------------------------------------------------------------
# identity.created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_created_provisions_free_plan(client, db_session, hmac_secret):
    payload = {"windy_identity_id": "new-user-1", "tier": "free"}
    body = json.dumps(payload).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={
            "X-Windy-Signature": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["tier"] == "free"

    plan = (
        await db_session.execute(select(UserPlan).where(UserPlan.identity_id == "new-user-1"))
    ).scalar_one()
    assert plan.quota_bytes == 5_368_709_120
    assert plan.frozen is False


@pytest.mark.asyncio
async def test_identity_created_links_passport(client, db_session, hmac_secret):
    payload = {
        "windy_identity_id": "new-user-2",
        "tier": "pro",
        "passport_number": "ET-99999",
    }
    body = json.dumps(payload).encode()
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={"X-Windy-Signature": _sign(body)},
    )
    assert resp.status_code == 201

    bridge = (
        await db_session.execute(
            select(IdentityBridge).where(IdentityBridge.passport_number == "ET-99999")
        )
    ).scalar_one()
    assert bridge.windy_identity_id == "new-user-2"


@pytest.mark.asyncio
async def test_identity_created_rejects_bad_signature(client, hmac_secret):
    body = b'{"windy_identity_id":"x","tier":"free"}'
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={"X-Windy-Signature": "deadbeef"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_identity_created_rejects_when_secret_unset(client):
    body = b'{"windy_identity_id":"x","tier":"free"}'
    # No hmac_secret fixture → settings.identity_webhook_secret is empty
    resp = await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={"X-Windy-Signature": "anything"},
    )
    assert resp.status_code in (403, 503)


@pytest.mark.asyncio
async def test_identity_created_is_idempotent(client, db_session, hmac_secret):
    payload = {"windy_identity_id": "repeat-1", "tier": "free"}
    body = json.dumps(payload).encode()
    for _ in range(3):
        resp = await client.post(
            "/api/v1/webhooks/identity/created",
            content=body,
            headers={"X-Windy-Signature": _sign(body)},
        )
        assert resp.status_code == 201

    rows = (
        (await db_session.execute(select(UserPlan).where(UserPlan.identity_id == "repeat-1")))
        .scalars()
        .all()
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# passport.revoked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passport_revoked_freezes_plan(client, db_session, hmac_secret, eternitas_es256):
    # Provision an identity with bridge
    payload = {
        "windy_identity_id": "revoke-me",
        "tier": "pro",
        "passport_number": "ET-42",
    }
    body = json.dumps(payload).encode()
    await client.post(
        "/api/v1/webhooks/identity/created",
        content=body,
        headers={"X-Windy-Signature": _sign(body)},
    )

    # Eternitas signs a revocation token
    revoke_token = eternitas_es256({
        "sub": "ET-42",
        "passport_number": "ET-42",
        "reason": "ban",
        "exp": int(time.time()) + 60,
        "jti": "wave2-rev-42",  # Wave 7 G14: required for replay dedup
    })

    resp = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={"token": revoke_token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "frozen"

    plan = (
        await db_session.execute(select(UserPlan).where(UserPlan.identity_id == "revoke-me"))
    ).scalar_one()
    assert plan.frozen is True


@pytest.mark.asyncio
async def test_passport_revoked_rejects_unsigned(client, eternitas_es256):
    resp = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={"passport_number": "ET-99", "reason": "n/a"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_passport_revoked_unknown_passport(client, eternitas_es256):
    token = eternitas_es256({
        "sub": "ET-NOPE",
        "passport_number": "ET-NOPE",
        "exp": int(time.time()) + 60,
        "jti": "wave2-rev-nope",  # Wave 7 G14: required for replay dedup
    })
    resp = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={"token": token},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unknown_passport"
