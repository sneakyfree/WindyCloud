"""Live quota-multiplier verification per band (Wave 4 step 3).

For each seeded test passport, we:
  1. Hit the live Trust API and read back the effective `tier_multiplier`.
  2. Run `allocate_plan()` against an in-memory DB and confirm that quota
     equals `base_tier_quota * live_multiplier`.
  3. For the revoked passport, also exercise the upload gate and confirm
     it rejects with 403 frozen_account.

We assert what the live contract says — the server applies
`min(clearance_multiplier, band_multiplier)`, so a passport whose operator
has `top_secret` clearance will cap at 3.0 even in the `exceptional` band.
That's by design, documented in eternitas/docs/trust-api.md.

Skipped when Eternitas isn't reachable.
"""

from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app.config import settings
from api.app.db.models import Base, IdentityBridge, UserPlan
from api.app.routes.billing import allocate_plan
from api.app.services.trust_client import TrustClient, _reset_trust_client_for_testing

ETERNITAS_URL = os.environ.get("ETERNITAS_URL") or settings.eternitas_url

SEEDED_PASSPORTS = {
    "ET26-TEST-EXCP": "exceptional",
    "ET26-TEST-GOOD": "good",
    "ET26-TEST-FAIR": "fair",
    "ET26-TEST-POOR": "poor",
    "ET26-TEST-REVD": "critical",  # revoked status, critical band
}

# Pro tier base quota in bytes (matches settings.tier_quota_pro)
PRO_BASE = 107_374_182_400


def _eternitas_reachable() -> bool:
    try:
        return httpx.get(f"{ETERNITAS_URL}/health", timeout=1.5).status_code < 500
    except (httpx.HTTPError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _eternitas_reachable(),
    reason=f"Eternitas not reachable at {ETERNITAS_URL}",
)


@pytest.fixture
async def fresh_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def live_trust_client(monkeypatch):
    """Point the global trust client at the live Eternitas."""
    from api.app.services import trust_client as tc_mod

    _reset_trust_client_for_testing()
    live = TrustClient(base_url=ETERNITAS_URL, use_mock=False)
    monkeypatch.setattr(tc_mod, "_trust_client", live)
    monkeypatch.setattr(tc_mod, "get_trust_client", lambda: live)
    # billing.py binds via "from api.app.services.trust_client import get_trust_client"
    # at function scope — but re-import just in case.
    from api.app.routes import billing as billing_mod

    monkeypatch.setattr(billing_mod, "get_trust_client", lambda: live, raising=False)
    yield
    _reset_trust_client_for_testing()


# ---------------------------------------------------------------------------
# Per-passport: confirm bands match the seed, then allocate + verify quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("passport,expected_band", list(SEEDED_PASSPORTS.items()))
async def test_live_band_matches_seed(passport, expected_band):
    """Each seeded passport reports the band Grant documented."""
    client = TrustClient(base_url=ETERNITAS_URL, use_mock=False)
    info = await client.get_trust(passport)
    assert info is not None, f"{passport} missing from Eternitas"
    assert info.band == expected_band, f"{passport}: expected band={expected_band} got {info.band}"


@pytest.mark.asyncio
@pytest.mark.parametrize("passport", list(SEEDED_PASSPORTS))
async def test_live_allocate_applies_server_multiplier(fresh_db, passport):
    """allocate_plan(pro) * live multiplier → the quota we store."""
    client = TrustClient(base_url=ETERNITAS_URL, use_mock=False)
    live = await client.get_trust(passport)
    assert live is not None

    plan = await allocate_plan(
        fresh_db,
        windy_identity_id=f"live-{passport}",
        tier="pro",
        passport_number=passport,
    )
    expected_quota = int(PRO_BASE * live.tier_multiplier)
    assert plan.quota_bytes == expected_quota, (
        f"{passport}: expected quota={expected_quota} got {plan.quota_bytes} "
        f"(live multiplier={live.tier_multiplier})"
    )
    assert plan.trust_multiplier_at_allocation == live.tier_multiplier


# ---------------------------------------------------------------------------
# Revoked passport: verify the frozen_account upload gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_passport_blocks_upload(fresh_db):
    """ET26-TEST-REVD: status=revoked → upload gate returns 403 frozen_account."""
    import json as _json

    from httpx import ASGITransport, AsyncClient

    from api.app.auth.dependencies import AuthenticatedUser, get_current_user
    from api.app.db.engine import get_db
    from api.app.main import create_app

    identity = "revd-human"
    fresh_db.add(
        IdentityBridge(
            windy_identity_id=identity,
            passport_number="ET26-TEST-REVD",
        )
    )
    fresh_db.add(
        UserPlan(
            identity_id=identity,
            plan_id="pro",
            tier="pro",
            quota_bytes=PRO_BASE,
        )
    )
    await fresh_db.commit()

    app = create_app()

    async def _user():
        return AuthenticatedUser(
            identity_id=identity,
            claims={"sub": identity},
            source="windy_pro",
        )

    async def _db():
        yield fresh_db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/storage/upload",
            files={"file": ("f.bin", b"abc", "application/octet-stream")},
            data={"metadata": _json.dumps({})},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "frozen_account"


# ---------------------------------------------------------------------------
# Revoked passport: allocated quota is 0 (multiplier 0.0)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_passport_allocates_zero_quota(fresh_db):
    client = TrustClient(base_url=ETERNITAS_URL, use_mock=False)
    live = await client.get_trust("ET26-TEST-REVD")
    assert live is not None
    assert live.status == "revoked"
    assert live.tier_multiplier == 0.0

    plan = await allocate_plan(
        fresh_db,
        windy_identity_id="live-revd-alloc",
        tier="pro",
        passport_number="ET26-TEST-REVD",
    )
    assert plan.quota_bytes == 0
    assert plan.trust_multiplier_at_allocation == 0.0
