"""Wave 12 H-3 — /api/v1/webhooks/passport/reinstated.

Mirror of the passport.revoked tests. Uses the same ES256 stub
fixture the Wave 2 tests use.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from api.app.db.models import IdentityBridge, UserPlan


@pytest.fixture
def eternitas_es256(monkeypatch):
    """Same stub as test_wave2_webhooks — duplicated here so this
    module stands alone. A shared conftest helper is a Wave 13 cleanup
    opportunity."""
    from api.app.auth import jwks as jwks_mod
    from api.app.routes import webhooks as webhooks_mod

    private_key = ec.generate_private_key(ec.SECP256R1())
    pem_pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pem_priv = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    class _StubValidator:
        def validate_token(self, token: str):
            return pyjwt.decode(token, pem_pub, algorithms=["ES256"])

    stub = _StubValidator()
    monkeypatch.setattr(jwks_mod, "_eternitas_validator", stub)
    monkeypatch.setattr(jwks_mod, "get_eternitas_validator", lambda: stub)
    monkeypatch.setattr(webhooks_mod, "get_eternitas_validator", lambda: stub)

    def _sign(claims: dict) -> str:
        return pyjwt.encode(claims, pem_priv, algorithm="ES256")

    return _sign


@pytest.mark.asyncio
async def test_reinstate_unfreezes_plan(client, db_session, eternitas_es256):
    """Frozen plan + valid ES256 reinstate token → frozen=False, 200."""
    db_session.add(
        IdentityBridge(
            windy_identity_id="wave12-reinstate-1",
            passport_number="ET-WAVE12-001",
        )
    )
    db_session.add(
        UserPlan(
            identity_id="wave12-reinstate-1",
            plan_id="free",
            tier="free",
            quota_bytes=5 * 1024**3,
            frozen=True,
        )
    )
    await db_session.commit()

    token = eternitas_es256(
        {
            "sub": "ET-WAVE12-001",
            "passport_number": "ET-WAVE12-001",
            "reason": "appeal-approved",
            "exp": int(time.time()) + 60,
        }
    )

    resp = await client.post(
        "/api/v1/webhooks/passport/reinstated",
        json={"token": token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "reinstated"
    assert body["was_frozen"] is True

    await db_session.commit()
    plan_row = await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "wave12-reinstate-1")
    )
    plan = plan_row.scalar_one()
    assert plan.frozen is False


@pytest.mark.asyncio
async def test_reinstate_idempotent_on_already_active(client, db_session, eternitas_es256):
    """Reinstating an already-active plan is a no-op 200 with
    was_frozen=False."""
    db_session.add(
        IdentityBridge(
            windy_identity_id="wave12-reinstate-2",
            passport_number="ET-WAVE12-002",
        )
    )
    db_session.add(
        UserPlan(
            identity_id="wave12-reinstate-2",
            plan_id="free",
            tier="free",
            quota_bytes=5 * 1024**3,
            frozen=False,
        )
    )
    await db_session.commit()

    token = eternitas_es256(
        {
            "sub": "ET-WAVE12-002",
            "passport_number": "ET-WAVE12-002",
            "exp": int(time.time()) + 60,
        }
    )
    resp = await client.post(
        "/api/v1/webhooks/passport/reinstated",
        json={"token": token},
    )
    assert resp.status_code == 200
    assert resp.json()["was_frozen"] is False


@pytest.mark.asyncio
async def test_reinstate_unknown_passport_no_op(client, eternitas_es256):
    """A reinstate for a passport we never bridged is a 200 with
    status=unknown_passport — no exception, no DB churn."""
    token = eternitas_es256(
        {
            "sub": "ET-NEVER-SEEN",
            "passport_number": "ET-NEVER-SEEN",
            "exp": int(time.time()) + 60,
        }
    )
    resp = await client.post(
        "/api/v1/webhooks/passport/reinstated",
        json={"token": token},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unknown_passport"


@pytest.mark.asyncio
async def test_reinstate_rejects_unsigned(client, eternitas_es256):
    resp = await client.post(
        "/api/v1/webhooks/passport/reinstated",
        json={"passport_number": "ET-X", "reason": "n/a"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reinstate_rejects_garbage_token(client, eternitas_es256):
    resp = await client.post(
        "/api/v1/webhooks/passport/reinstated",
        json={"token": "not.a.jwt"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reinstate_bridge_exists_but_no_plan(client, db_session, eternitas_es256):
    """Bridge row exists, no UserPlan yet — reinstate logs + 200 'no_plan',
    does NOT silently create a plan (allocate_plan + identity.created
    are the single sources of truth for plan creation)."""
    db_session.add(
        IdentityBridge(
            windy_identity_id="wave12-reinstate-3",
            passport_number="ET-WAVE12-003",
        )
    )
    await db_session.commit()

    token = eternitas_es256(
        {
            "sub": "ET-WAVE12-003",
            "passport_number": "ET-WAVE12-003",
            "exp": int(time.time()) + 60,
        }
    )
    resp = await client.post(
        "/api/v1/webhooks/passport/reinstated",
        json={"token": token},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_plan"

    # Confirm no UserPlan was magically created.
    plan_row = await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "wave12-reinstate-3")
    )
    assert plan_row.scalar_one_or_none() is None
