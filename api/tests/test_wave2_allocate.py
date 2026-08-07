"""Tests for POST /api/v1/billing/allocate (Wave 2 contract #1)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from api.app.config import settings
from api.app.db.models import UserPlan

TOKEN = "wave2-test-service-token"


@pytest.fixture
def service_token(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", TOKEN)
    return TOKEN


@pytest.mark.asyncio
async def test_allocate_creates_plan(client, db_session, service_token):
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-free-1", "tier": "free"},
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tier"] == "free"
    assert body["quota_bytes"] == settings.tier_quota_free
    assert body["identity_id"] == "id-free-1"

    row = (
        await db_session.execute(select(UserPlan).where(UserPlan.identity_id == "id-free-1"))
    ).scalar_one()
    assert row.tier == "free"
    assert row.frozen is False


@pytest.mark.asyncio
async def test_allocate_is_idempotent(client, db_session, service_token):
    for _ in range(2):
        resp = await client.post(
            "/api/v1/billing/allocate",
            json={"windy_identity_id": "id-pro-1", "tier": "pro"},
            headers={"X-Service-Token": service_token},
        )
        assert resp.status_code == 200

    rows = (
        (await db_session.execute(select(UserPlan).where(UserPlan.identity_id == "id-pro-1")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].tier == "pro"
    assert rows[0].quota_bytes == settings.tier_quota_pro


@pytest.mark.asyncio
async def test_allocate_upgrades_tier(client, db_session, service_token):
    await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-up-1", "tier": "free"},
        headers={"X-Service-Token": service_token},
    )
    resp = await client.post(
        "/api/v1/billing/allocate",
        # "ultra" is a DISPLAY alias; allocate normalizes it to `translate`.
        json={"windy_identity_id": "id-up-1", "tier": "ultra"},
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200
    assert resp.json()["quota_bytes"] == settings.tier_quota_translate


@pytest.mark.asyncio
async def test_allocate_rejects_unknown_tier(client, service_token):
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-bad", "tier": "platinum"},
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_allocate_requires_service_token(client):
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-x", "tier": "free"},
    )
    assert resp.status_code == 422  # missing required header


@pytest.mark.asyncio
async def test_allocate_rejects_bad_service_token(client, service_token):
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-x", "tier": "free"},
        headers={"X-Service-Token": "wrong-token"},
    )
    assert resp.status_code == 401


# ─── Authoritative quota from the account server (2026-08-07) ──────────────
#
# The account server owns entitlement for the whole ecosystem and sends the
# exact quota. Before this, Cloud mapped tier→bytes from its OWN private table
# and the two ladders disagreed by up to 170x (Cloud's "free" was 5 GB against
# the contract's 500 MB), so a paying customer's real quota depended on which
# service you asked.


@pytest.mark.asyncio
async def test_allocate_honours_explicit_quota_bytes(client, db_session, service_token):
    """An explicit quota_bytes overrides this repo's tier table."""
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={
            "windy_identity_id": "id-explicit-1",
            "tier": "translate_pro",
            "quota_bytes": 999_999_999,
        },
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["quota_bytes"] == 999_999_999
    assert resp.json()["quota_bytes"] != settings.tier_quota_translate_pro


@pytest.mark.asyncio
async def test_allocate_falls_back_to_table_without_quota_bytes(
    client, db_session, service_token
):
    """Callers that provision outside a purchase (identity.created, the
    windy-agent hatch) send no quota_bytes and must still get the right tier
    quota — which is why the fallback table has to mirror the contract."""
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-fallback-1", "tier": "translate_pro"},
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["quota_bytes"] == settings.tier_quota_translate_pro


@pytest.mark.asyncio
async def test_allocate_rejects_negative_quota(client, db_session, service_token):
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={
            "windy_identity_id": "id-negative-1",
            "tier": "pro",
            "quota_bytes": -1,
        },
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_allocate_normalizes_display_aliases(client, db_session, service_token):
    """`ultra`/`max` are DISPLAY names elsewhere in the ecosystem but were this
    repo's canonical ids until 2026-08-07. An old client sending either must
    land on the canonical id, never create a fifth vocabulary."""
    for alias, canonical in (("ultra", "translate"), ("max", "translate_pro")):
        resp = await client.post(
            "/api/v1/billing/allocate",
            json={"windy_identity_id": f"id-alias-{alias}", "tier": alias},
            headers={"X-Service-Token": service_token},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["tier"] == canonical

        row = (
            await db_session.execute(
                select(UserPlan).where(UserPlan.identity_id == f"id-alias-{alias}")
            )
        ).scalar_one()
        assert row.tier == canonical, "an alias must never be stored"
