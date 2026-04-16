"""Tests for POST /api/v1/billing/allocate (Wave 2 contract #1)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

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
    assert body["quota_bytes"] == 5_368_709_120
    assert body["identity_id"] == "id-free-1"

    row = (await db_session.execute(
        select(UserPlan).where(UserPlan.identity_id == "id-free-1")
    )).scalar_one()
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
        await db_session.execute(
            select(UserPlan).where(UserPlan.identity_id == "id-pro-1")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].tier == "pro"
    assert rows[0].quota_bytes == 107_374_182_400


@pytest.mark.asyncio
async def test_allocate_upgrades_tier(client, db_session, service_token):
    await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-up-1", "tier": "free"},
        headers={"X-Service-Token": service_token},
    )
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "id-up-1", "tier": "ultra"},
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200
    assert resp.json()["quota_bytes"] == 1_099_511_627_776


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
