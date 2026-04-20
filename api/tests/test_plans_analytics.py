"""Tests for per-user plans, upgrade flow, and analytics."""

from __future__ import annotations

import pytest

from api.app.config import settings


@pytest.mark.asyncio
async def test_get_plan_default_free(client):
    """User with no plan record gets free tier (Wave 2 vocab: 5 GB)."""
    resp = await client.get(
        "/api/v1/billing/plan",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"] == "free"
    assert body["quota_bytes"] == 5_368_709_120  # 5 GB — tier_quota_free
    assert body["price_cents_per_month"] == 0
    assert "upgrade_url" in body


@pytest.mark.asyncio
async def test_upgrade_plan(client):
    """Upgrading plan increases quota (Wave 2 vocab: pro = 100 GB)."""
    resp = await client.post(
        "/api/v1/billing/plan/upgrade",
        json={"plan_id": "pro"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["plan_id"] == "pro"
    assert resp.json()["quota_bytes"] == 107_374_182_400  # 100 GB — tier_quota_pro

    # Verify plan persists
    resp = await client.get(
        "/api/v1/billing/plan",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.json()["plan_id"] == "pro"


@pytest.mark.asyncio
async def test_upgrade_invalid_plan(client):
    """Invalid plan returns 400."""
    resp = await client.post(
        "/api/v1/billing/plan/upgrade",
        json={"plan_id": "nonexistent"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upgraded_quota_enforced(client):
    """After upgrade, user can upload beyond free tier quota."""
    from api.app.config import settings

    original = settings.default_storage_quota
    settings.default_storage_quota = 10  # Tiny free quota

    # Upload blocked on free tier
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("big.bin", b"x" * 20, "application/octet-stream")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 507

    # Upgrade to pro
    await client.post(
        "/api/v1/billing/plan/upgrade",
        json={"plan_id": "pro"},
        headers={"Authorization": "Bearer fake"},
    )

    # Now upload succeeds
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("big.bin", b"x" * 20, "application/octet-stream")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200

    settings.default_storage_quota = original


@pytest.mark.asyncio
async def test_analytics_daily(client, monkeypatch):
    """Analytics daily endpoint returns data (with admin-gate unlocked).

    Wave 14 P1 gated these on require_admin; the default TEST_USER in
    conftest isn't admin unless we add its identity to the allowlist.
    """
    monkeypatch.setattr(settings, "admin_identity_ids", "test-user-001")
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/analytics/daily",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    days = resp.json()["days"]
    assert len(days) >= 1
    assert days[0]["files_uploaded"] >= 1


@pytest.mark.asyncio
async def test_analytics_summary(client, monkeypatch):
    """Analytics summary aggregates all events (admin-gate unlocked)."""
    monkeypatch.setattr(settings, "admin_identity_ids", "test-user-001")
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/analytics/summary",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_files_uploaded"] >= 1
    assert body["total_storage_bytes"] >= 5
