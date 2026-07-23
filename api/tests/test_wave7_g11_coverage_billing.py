"""G11 coverage push — billing.py.

Baseline 54% on main; targets the money-handling endpoints Grant
specifically flagged: billing_history (both branches), billing_estimate,
billing_sync, billing_summary, get_plan, upgrade_plan (error + happy).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from api.app.db.models import BillingSnapshot, ComputeUsageRecord, FileRecord, UserPlan


@pytest.mark.asyncio
async def test_billing_usage_includes_storage_and_compute(client, db_session):
    # Seed a file + a compute record
    db_session.add(
        FileRecord(
            id="f-usage-1",
            identity_id="test-user-001",
            product="general",
            file_type="file",
            filename="a.bin",
            storage_key="k1",
            size_bytes=1024,
        )
    )
    db_session.add(
        ComputeUsageRecord(
            id="cu-1",
            identity_id="test-user-001",
            month=datetime.utcnow().strftime("%Y-%m"),
            total_seconds=120.0,
            total_jobs=2,
            total_cost_cents=50,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/billing/usage", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["storage"]["used_bytes"] == 1024
    assert body["storage"]["file_count"] == 1
    assert body["compute"]["total_seconds"] == 120.0
    assert body["compute"]["total_jobs"] == 2
    assert body["total_cost_cents"] == 50


@pytest.mark.asyncio
async def test_billing_history_from_snapshots(client, db_session):
    """Snapshots exist → history reads from them, grouped by month."""
    # Two snapshots in the same month, latest wins
    db_session.add(
        BillingSnapshot(
            id="s-1",
            identity_id="test-user-001",
            date="2026-04-01",
            storage_bytes=1_000_000_000,
            file_count=10,
            compute_seconds=60.0,
            compute_cost_cents=20,
        )
    )
    db_session.add(
        BillingSnapshot(
            id="s-2",
            identity_id="test-user-001",
            date="2026-04-15",
            storage_bytes=2_000_000_000,
            file_count=20,
            compute_seconds=120.0,
            compute_cost_cents=40,
        )
    )
    db_session.add(
        BillingSnapshot(
            id="s-3",
            identity_id="test-user-001",
            date="2026-03-10",
            storage_bytes=500_000_000,
            file_count=5,
            compute_seconds=30.0,
            compute_cost_cents=10,
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/billing/history?months=6",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    months = {e["month"] for e in entries}
    assert "2026-04" in months
    assert "2026-03" in months
    # April entry should reflect the latest-in-month snapshot (s-2).
    april = next(e for e in entries if e["month"] == "2026-04")
    assert april["storage_bytes"] == 2_000_000_000
    assert april["compute_cost_cents"] == 40


@pytest.mark.asyncio
async def test_billing_history_fallback_to_compute_usage(client, db_session):
    """No snapshots → falls back to ComputeUsageRecord rows."""
    db_session.add(
        ComputeUsageRecord(
            id="cu-hist-1",
            identity_id="test-user-001",
            month="2026-02",
            total_seconds=300.0,
            total_jobs=5,
            total_cost_cents=75,
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/billing/history?months=3",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert any(e["month"] == "2026-02" and e["compute_cost_cents"] == 75 for e in entries)


@pytest.mark.asyncio
async def test_billing_estimate(client, db_session):
    db_session.add(
        FileRecord(
            id="f-est-1",
            identity_id="test-user-001",
            product="general",
            file_type="file",
            filename="big.bin",
            storage_key="ke",
            size_bytes=5_000_000_000,  # 5 GB, in free tier
        )
    )
    db_session.add(
        ComputeUsageRecord(
            id="cu-est-1",
            identity_id="test-user-001",
            month=datetime.utcnow().strftime("%Y-%m"),
            total_seconds=60.0,
            total_jobs=1,
            total_cost_cents=30,
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/billing/estimate",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["compute_cost_cents"] == 30
    assert body["total_estimated_cents"] >= 30


@pytest.mark.asyncio
async def test_billing_sync_aggregates_product_usage(client, db_session):
    db_session.add(
        FileRecord(
            id="f-sync-1",
            identity_id="test-user-001",
            product="windy_mail",
            file_type="mail_backup",
            filename="dump.gz",
            storage_key="k-sync",
            size_bytes=50_000_000,
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/billing/sync",
        json={"windy_identity_id": "test-user-001"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["identity_id"] == "test-user-001"
    assert body["storage_bytes"] == 50_000_000
    assert body["storage_file_count"] == 1


@pytest.mark.asyncio
async def test_billing_summary_agent_friendly(client, db_session):
    db_session.add(
        FileRecord(
            id="f-sum-1",
            identity_id="test-user-001",
            product="general",
            file_type="file",
            filename="s.bin",
            storage_key="k-sum",
            size_bytes=500_000,
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/billing/summary",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "storage_used" in body
    assert "storage_quota" in body
    assert "storage_percent" in body
    assert "compute_minutes_used" in body


@pytest.mark.asyncio
async def test_get_plan_reads_existing_plan(client, db_session):
    """On this branch /billing/plan returns quotas from PLAN_TIERS (main
    vocab — free/basic/pro/ultra). G17+G18 unifies to tier_quota_*; this
    test tracks the main-branch numbers until that PR merges."""
    from api.app.routes.billing import PLAN_TIERS

    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="pro",
            tier="pro",
            quota_bytes=PLAN_TIERS["pro"]["quota_bytes"],
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/billing/plan",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"] == "pro"
    assert body["quota_bytes"] == PLAN_TIERS["pro"]["quota_bytes"]


@pytest.mark.asyncio
async def test_upgrade_plan_unknown_tier_400(client, monkeypatch):
    # [B3 fix] route is service-authenticated: X-Service-Token + identity in body
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", "cov-tok")
    resp = await client.post(
        "/api/v1/billing/plan/upgrade",
        json={"plan_id": "titanium", "windy_identity_id": "cov-user"},
        headers={"X-Service-Token": "cov-tok"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_allocate_plan_unknown_tier_400(client, monkeypatch):
    """allocate_plan's ValueError → HTTPException 400 path."""
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", "cov-tok")
    resp = await client.post(
        "/api/v1/billing/allocate",
        json={"windy_identity_id": "alloc-cov", "tier": "platinum"},
        headers={"X-Service-Token": "cov-tok"},
    )
    assert resp.status_code == 400
