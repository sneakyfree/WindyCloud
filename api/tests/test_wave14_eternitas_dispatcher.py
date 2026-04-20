"""Wave 14 P0 — /webhooks/eternitas dispatcher.

Eternitas fans every event type to a single per-subscriber URL
(`https://cloud.windyword.ai/webhooks/eternitas`). This suite verifies
the new no-prefix dispatcher routes correctly and that all existing
handler semantics (HMAC verification, JWT verification, replay
rejection, signature failure, unknown-event-ignore) remain intact when
invoked through the dispatcher.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import select

from api.app.config import settings
from api.app.db.models import IdentityBridge, UserPlan

TRUST_SECRET = "wave14-test-trust-secret"


@pytest.fixture(autouse=True)
def configure_eternitas(monkeypatch):
    monkeypatch.setattr(settings, "eternitas_webhook_secret", TRUST_SECRET)


def _sign_hmac(body: bytes, secret: str = TRUST_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# trust.changed: HMAC-signed raw-body path through the dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_routes_trust_changed_to_hmac_handler(client):
    body = json.dumps(
        {
            "event": "trust.changed",
            "passport_number": "ET26-ABCD-1234",
            "reason": "manual_adjustment",
        }
    ).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "trust.changed",
            "X-Eternitas-Signature": _sign_hmac(body),
            "X-Eternitas-Timestamp": str(int(time.time())),
            "X-Eternitas-Delivery": "dlv-trust-1",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "invalidated"
    assert data["passport_number"] == "ET26-ABCD-1234"


@pytest.mark.asyncio
async def test_dispatcher_rejects_trust_changed_with_bad_hmac(client):
    body = json.dumps(
        {"event": "trust.changed", "passport_number": "ET26-ABCD-1234"}
    ).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "trust.changed",
            "X-Eternitas-Signature": "sha256=" + "deadbeef" * 8,
            "X-Eternitas-Timestamp": str(int(time.time())),
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dispatcher_rejects_trust_changed_without_signature(client):
    body = json.dumps(
        {"event": "trust.changed", "passport_number": "ET26-ABCD-1234"}
    ).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "trust.changed",
        },
    )
    assert resp.status_code == 400
    assert "X-Eternitas-Signature" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_dispatcher_trust_changed_stale_timestamp(client):
    body = json.dumps({"event": "trust.changed", "passport_number": "ET26-ABCD"}).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "trust.changed",
            "X-Eternitas-Signature": _sign_hmac(body),
            "X-Eternitas-Timestamp": str(int(time.time()) - 600),
        },
    )
    assert resp.status_code == 400
    assert "Stale" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# passport.revoked: signed-JWT path through the dispatcher
# ---------------------------------------------------------------------------


def _eternitas_token(claims: dict, pub_setup):
    """Mint an ES256 token signed by the stubbed Eternitas key.

    Includes `sub` by default because the Eternitas validator inherits
    the Wave-7 require-sub contract (Wave 14 only loosened the *Pro*
    validator; Eternitas tokens have always carried sub=passport_number).
    """
    import jwt as pyjwt

    priv_pem = pub_setup["priv_pem"]
    base = {
        "exp": int(time.time()) + 300,
        "jti": claims.get("jti", "jti-default"),
        "sub": claims.get("passport_number") or claims.get("sub") or "sub-default",
    }
    base.update(claims)
    return pyjwt.encode(base, priv_pem, algorithm="ES256", headers={"kid": "et-test"})


@pytest.fixture
def stub_eternitas_validator(monkeypatch):
    """Swap get_eternitas_validator() to a validator that trusts an
    ephemeral ES256 keypair — no network fetch, no JWKS server."""
    from unittest.mock import MagicMock

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from api.app.auth import jwks as jwks_mod
    from api.app.auth.jwks import JWKSValidator

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_key = priv.public_key()

    validator = JWKSValidator("http://stub", audience="", issuer="")
    stub_client = MagicMock()
    signing_stub = MagicMock()
    signing_stub.key = pub_key
    stub_client.get_signing_key_from_jwt.return_value = signing_stub
    validator._jwk_client = stub_client
    validator._last_fetch = time.monotonic()

    monkeypatch.setattr(jwks_mod, "get_eternitas_validator", lambda: validator)
    # Also patch the webhooks module's reference (it imports the function
    # at module-scope).
    from api.app.routes import webhooks as _wh_mod

    monkeypatch.setattr(_wh_mod, "get_eternitas_validator", lambda: validator)

    return {"priv_pem": priv_pem, "pub_key": pub_key, "validator": validator}


@pytest.mark.asyncio
async def test_dispatcher_routes_passport_revoked_to_jwt_handler(
    client, db_session, stub_eternitas_validator
):
    # Seed the identity bridge so the revocation has a target to freeze.
    passport = "ET26-REVK-9999"
    db_session.add(
        IdentityBridge(
            windy_identity_id="user-revoke-target",
            passport_number=passport,
            linked_by="test-setup",
        )
    )
    db_session.add(
        UserPlan(
            identity_id="user-revoke-target",
            plan_id="free",
            tier="free",
            quota_bytes=5_368_709_120,
            frozen=False,
        )
    )
    await db_session.commit()

    token = _eternitas_token(
        {"passport_number": passport, "jti": "revoke-jti-1", "reason": "test"},
        stub_eternitas_validator,
    )
    body = json.dumps({"event": "passport.revoked", "token": token}).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "passport.revoked",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "frozen"

    # Verify UserPlan.frozen actually flipped.
    refreshed = await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "user-revoke-target")
    )
    plan = refreshed.scalar_one()
    assert plan.frozen is True


@pytest.mark.asyncio
async def test_dispatcher_routes_passport_reinstated_to_jwt_handler(
    client, db_session, stub_eternitas_validator
):
    passport = "ET26-REIN-7777"
    db_session.add(
        IdentityBridge(
            windy_identity_id="user-reinstate-target",
            passport_number=passport,
            linked_by="test-setup",
        )
    )
    db_session.add(
        UserPlan(
            identity_id="user-reinstate-target",
            plan_id="free",
            tier="free",
            quota_bytes=5_368_709_120,
            frozen=True,
        )
    )
    await db_session.commit()

    token = _eternitas_token(
        {"passport_number": passport, "jti": "reinstate-jti-1"},
        stub_eternitas_validator,
    )
    body = json.dumps({"event": "passport.reinstated", "token": token}).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "passport.reinstated",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "reinstated"
    assert resp.json()["was_frozen"] is True


# ---------------------------------------------------------------------------
# Event-type resolution & error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_falls_back_to_body_event_when_header_missing(
    client, stub_eternitas_validator
):
    """Eternitas sometimes sets only the body.event field (older
    platform versions). The dispatcher must still route."""
    body = json.dumps(
        {"event": "trust.changed", "passport_number": "ET26-BODY-EVENT"}
    ).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            # No X-Eternitas-Event header.
            "X-Eternitas-Signature": _sign_hmac(body),
            "X-Eternitas-Timestamp": str(int(time.time())),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "invalidated"


@pytest.mark.asyncio
async def test_dispatcher_missing_both_header_and_body_event(client):
    resp = await client.post(
        "/webhooks/eternitas",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "Missing X-Eternitas-Event" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_dispatcher_unknown_event_returns_200_ignored(client):
    resp = await client.post(
        "/webhooks/eternitas",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "passport.renewed",  # not wired on Cloud
        },
    )
    # 200 with ignored — matches Stripe webhook convention so Eternitas
    # doesn't retry-then-auto-deactivate on a benign unknown event.
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ignored"
    assert data["event_type"] == "passport.renewed"


@pytest.mark.asyncio
async def test_dispatcher_event_type_case_insensitive(client):
    body = json.dumps({"passport_number": "ET-CASE"}).encode()
    resp = await client.post(
        "/webhooks/eternitas",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "TRUST.CHANGED",
            "X-Eternitas-Signature": _sign_hmac(body),
            "X-Eternitas-Timestamp": str(int(time.time())),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "invalidated"


@pytest.mark.asyncio
async def test_dispatcher_passport_event_with_invalid_json_body(client):
    resp = await client.post(
        "/webhooks/eternitas",
        content=b"not-json-at-all",
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Event": "passport.revoked",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Canonical per-event endpoints still work (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_trust_changed_endpoint_still_works(client):
    """The /api/v1/webhooks/trust/changed route must continue to work
    alongside the new dispatcher — internal callers and tests that hit
    it directly shouldn't break."""
    body = json.dumps({"event": "trust.changed", "passport_number": "ET-LEGACY"}).encode()
    resp = await client.post(
        "/api/v1/webhooks/trust/changed",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Eternitas-Signature": _sign_hmac(body),
            "X-Eternitas-Timestamp": str(int(time.time())),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "invalidated"
