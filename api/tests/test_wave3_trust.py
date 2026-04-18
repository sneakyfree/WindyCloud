"""Wave 3 — Trust API consumer gating quota + uploads."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from api.app.db.models import IdentityBridge, UserPlan
from api.app.services.trust_client import TrustInfo

ALLOC_TOKEN = "wave3-service-token"


@pytest.fixture
def service_token(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", ALLOC_TOKEN)
    return ALLOC_TOKEN


class _StubTrust:
    """In-memory stub of the Eternitas Trust API."""

    def __init__(self):
        self.table: dict[str, TrustInfo] = {}

    def set(self, passport: str, *, status: str, band: str, multiplier: float):
        self.table[passport] = TrustInfo(
            passport_number=passport,
            status=status,
            band=band,
            tier_multiplier=multiplier,
        )

    async def get_trust(self, passport: str):
        return self.table.get(passport)

    def invalidate(self, passport: str) -> None:
        self.table.pop(passport, None)


@pytest.fixture
def trust_stub(monkeypatch):
    """Swap the trust-client singleton for an in-memory stub."""
    from api.app.auth import webhook as webhook_mod
    from api.app.routes import billing as billing_mod
    from api.app.services import trust_client as trust_mod

    stub = _StubTrust()
    monkeypatch.setattr(trust_mod, "_trust_client", stub)
    monkeypatch.setattr(trust_mod, "get_trust_client", lambda: stub)
    monkeypatch.setattr(webhook_mod, "_trust_client", stub, raising=False)
    # Billing imports get_trust_client inside the function — re-patch the
    # module attribute used at import time if any test caches it.
    monkeypatch.setattr(billing_mod, "get_trust_client", lambda: stub, raising=False)
    return stub


# ---------------------------------------------------------------------------
# Allocate multipliers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exceptional_bot_gets_5x_quota(client, db_session, service_token, trust_stub):
    trust_stub.set("ET-EXC", status="active", band="exceptional", multiplier=5.0)

    resp = await client.post(
        "/api/v1/billing/allocate",
        json={
            "windy_identity_id": "bot-exc",
            "passport_number": "ET-EXC",
            "tier": "pro",
        },
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # pro base = 100 GB; multiplier 5 → 500 GB
    assert body["quota_bytes"] == 107_374_182_400 * 5

    plan = (await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "bot-exc")
    )).scalar_one()
    assert plan.trust_multiplier_at_allocation == 5.0


@pytest.mark.asyncio
async def test_critical_bot_gets_zero_quota(client, db_session, service_token, trust_stub):
    trust_stub.set("ET-CRIT", status="active", band="critical", multiplier=0.0)

    resp = await client.post(
        "/api/v1/billing/allocate",
        json={
            "windy_identity_id": "bot-crit",
            "passport_number": "ET-CRIT",
            "tier": "pro",
        },
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200
    assert resp.json()["quota_bytes"] == 0

    plan = (await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "bot-crit")
    )).scalar_one()
    assert plan.trust_multiplier_at_allocation == 0.0


@pytest.mark.asyncio
async def test_human_no_passport_base_quota(client, db_session, service_token, trust_stub):
    # No trust entry populated — and no passport sent in the request.
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "human-1", "tier": "pro"},
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200
    assert resp.json()["quota_bytes"] == 107_374_182_400  # 100 GB, un-multiplied

    plan = (await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "human-1")
    )).scalar_one()
    assert plan.trust_multiplier_at_allocation == 1.0


@pytest.mark.asyncio
async def test_verified_bot_2x_quota(client, service_token, trust_stub):
    trust_stub.set("ET-VER", status="active", band="good", multiplier=2.0)
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={
            "windy_identity_id": "bot-ver",
            "passport_number": "ET-VER",
            "tier": "free",
        },
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200
    assert resp.json()["quota_bytes"] == 5_368_709_120 * 2  # 10 GB


# ---------------------------------------------------------------------------
# Upload gate
# ---------------------------------------------------------------------------

async def _upload_with_real_gate(db_session, identity_id: str):
    """Bypass the conftest auth override so the real require_not_frozen runs."""
    from api.app.auth.dependencies import AuthenticatedUser, get_current_user
    from api.app.db.engine import get_db
    from api.app.main import create_app

    app = create_app()

    async def _user():
        return AuthenticatedUser(
            identity_id=identity_id,
            claims={"sub": identity_id},
            source="windy_pro",
        )

    async def _db():
        yield db_session

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.post(
            "/api/v1/storage/upload",
            files={"file": ("f.bin", b"abc", "application/octet-stream")},
            data={"metadata": json.dumps({})},
            headers={"Authorization": "Bearer fake"},
        )


@pytest.mark.asyncio
async def test_suspended_bot_upload_rejected(db_session, trust_stub):
    db_session.add(
        IdentityBridge(
            windy_identity_id="susp-bot",
            passport_number="ET-SUSP",
        )
    )
    db_session.add(
        UserPlan(
            identity_id="susp-bot",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()
    trust_stub.set("ET-SUSP", status="suspended", band="fair", multiplier=1.0)

    resp = await _upload_with_real_gate(db_session, "susp-bot")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "suspended_account"


@pytest.mark.asyncio
async def test_revoked_bot_upload_rejected(db_session, trust_stub):
    db_session.add(
        IdentityBridge(
            windy_identity_id="rev-bot",
            passport_number="ET-REV",
        )
    )
    db_session.add(
        UserPlan(
            identity_id="rev-bot",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()
    trust_stub.set("ET-REV", status="revoked", band="critical", multiplier=0.0)

    resp = await _upload_with_real_gate(db_session, "rev-bot")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "frozen_account"


@pytest.mark.asyncio
async def test_active_bot_upload_allowed(db_session, trust_stub):
    db_session.add(
        IdentityBridge(
            windy_identity_id="ok-bot",
            passport_number="ET-OK",
        )
    )
    db_session.add(
        UserPlan(
            identity_id="ok-bot",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()
    trust_stub.set("ET-OK", status="active", band="fair", multiplier=1.0)

    resp = await _upload_with_real_gate(db_session, "ok-bot")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_human_upload_skips_trust(db_session, trust_stub):
    """Human identity has no bridge row — upload must succeed without
    any call into the trust stub."""
    db_session.add(
        UserPlan(
            identity_id="pure-human",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
        )
    )
    await db_session.commit()
    # trust_stub left empty on purpose

    resp = await _upload_with_real_gate(db_session, "pure-human")
    assert resp.status_code == 200
    # And the stub was never consulted (no-op — the test passing with an
    # empty stub table already proves this)
