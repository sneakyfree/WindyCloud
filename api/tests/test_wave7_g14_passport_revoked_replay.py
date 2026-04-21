"""GAP G14: passport-revoked webhook rejects replays.

Pre-G14 the handler validated the Eternitas-signed JWT but did no
nonce / jti dedup. An attacker who observed a revocation token could
re-POST it to re-trigger the freeze path (and any future side effects
like audit rows, notifications, reputation events). Post-G14: jti is
required, duplicate deliveries return `status: duplicate` without
re-processing.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from api.app.db.models import IdentityBridge, UserPlan


def _es256_keypair():
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return priv_pem, priv.public_key()


@pytest.fixture
def eternitas_es256(monkeypatch):
    """Patch the Eternitas JWKSValidator to accept tokens signed by a
    locally-generated key pair. Token minter returned to the test."""
    from api.app.auth import jwks as jwks_mod
    from api.app.routes import webhooks as webhooks_mod

    priv_pem, pub_key = _es256_keypair()

    class _StubValidator:
        def validate_token(self, token: str):
            return pyjwt.decode(token, pub_key, algorithms=["ES256"])

    stub = _StubValidator()
    monkeypatch.setattr(jwks_mod, "_eternitas_validator", stub)
    monkeypatch.setattr(jwks_mod, "get_eternitas_validator", lambda: stub)
    monkeypatch.setattr(webhooks_mod, "get_eternitas_validator", lambda: stub)

    # Reset the dedup set between tests.
    webhooks_mod._seen_revocation_jtis.clear()

    def _sign(**claims) -> str:
        base = {
            "sub": claims.get("passport_number", "ET-JTI-1"),
            "exp": int(time.time()) + 300,
        }
        base.update(claims)
        return pyjwt.encode(base, priv_pem, algorithm="ES256")

    return _sign


async def _seed_bridge_and_plan(db_session, identity: str, passport: str):
    db_session.add(IdentityBridge(windy_identity_id=identity, passport_number=passport))
    db_session.add(
        UserPlan(
            identity_id=identity,
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_revocation_requires_jti(client, eternitas_es256):
    """A token with no jti is rejected with 400."""
    token_no_jti = eternitas_es256(
        passport_number="ET-NO-JTI",
        # explicitly don't set jti
    )
    resp = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={"token": token_no_jti},
    )
    assert resp.status_code == 400
    assert "jti" in resp.text.lower()


@pytest.mark.asyncio
async def test_first_revocation_freezes_plan(client, db_session, eternitas_es256):
    await _seed_bridge_and_plan(db_session, "g14-user-1", "ET-G14-1")

    token = eternitas_es256(
        jti="rev-001",
        passport_number="ET-G14-1",
    )
    resp = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={"token": token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "frozen"


@pytest.mark.asyncio
async def test_replayed_revocation_is_a_no_op(client, db_session, eternitas_es256):
    """Same jti posted twice → first freezes, second returns duplicate."""
    await _seed_bridge_and_plan(db_session, "g14-user-2", "ET-G14-2")

    token = eternitas_es256(
        jti="rev-replay-me",
        passport_number="ET-G14-2",
    )
    r1 = await client.post("/api/v1/webhooks/passport/revoked", json={"token": token})
    r2 = await client.post("/api/v1/webhooks/passport/revoked", json={"token": token})

    assert r1.status_code == 200 and r1.json()["status"] == "frozen"
    assert r2.status_code == 200 and r2.json()["status"] == "duplicate"
    assert r2.json()["jti"] == "rev-replay-me"


@pytest.mark.asyncio
async def test_different_jti_for_same_passport_processed(client, db_session, eternitas_es256):
    """Two revocation events for the same passport (different jti) both
    process — e.g., revoke → reinstate → revoke again with new jti."""
    await _seed_bridge_and_plan(db_session, "g14-user-3", "ET-G14-3")

    t1 = eternitas_es256(jti="rev-a", passport_number="ET-G14-3")
    t2 = eternitas_es256(jti="rev-b", passport_number="ET-G14-3")

    r1 = await client.post("/api/v1/webhooks/passport/revoked", json={"token": t1})
    r2 = await client.post("/api/v1/webhooks/passport/revoked", json={"token": t2})

    # Both process — second one is still "frozen" (idempotent DB side effect)
    # because we don't know it's a double-revoke without business logic.
    assert r1.status_code == 200 and r1.json()["status"] == "frozen"
    assert r2.status_code == 200 and r2.json()["status"] == "frozen"


@pytest.mark.asyncio
async def test_expired_token_still_rejected_by_pyjwt(client, eternitas_es256):
    """Even with a jti, an expired token must not get past signature check."""
    token = eternitas_es256(
        jti="rev-expired",
        passport_number="ET-EXPIRED",
        exp=int(time.time()) - 10,  # 10s in the past
    )
    resp = await client.post(
        "/api/v1/webhooks/passport/revoked",
        json={"token": token},
    )
    assert resp.status_code == 403
