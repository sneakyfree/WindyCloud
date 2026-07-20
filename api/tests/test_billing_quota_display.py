"""Regression tests — billing endpoints must report the USER'S quota.

Bug: /billing/usage and /billing/summary reported
`settings.default_storage_quota` (5 GB) and /billing/plan returned the
static tier table, discarding `UserPlan.quota_bytes` — which carries the
effective quota (base tier quota x Eternitas trust multiplier, applied
at allocation, see routes/billing.py::allocate_plan). A 100 GB Pro
customer was told they had 5 GB.

These tests seed a UserPlan with a quota_bytes value that matches NO
tier-table entry and NOT the default, so a pass proves the number came
from the user's plan row rather than from any static map.

Fallback contract (documented): an identity with no UserPlan row yet is
shown `settings.default_storage_quota` — the same number the upload gate
enforces via services/quota.py::get_quota_bytes.
"""

from __future__ import annotations

import pytest

from api.app.config import settings
from api.app.db.models import FileRecord, UserPlan

# 200 GB — deliberately equal to NO tier quota (free 5 GB, pro 100 GB,
# ultra 1 TB, max 5 TB) and not to default_storage_quota. E.g. a "pro"
# plan allocated with a 2.0 trust multiplier.
EFFECTIVE_QUOTA = 214_748_364_800

AUTH = {"Authorization": "Bearer fake"}


def _seed_plan(db_session, quota_bytes: int = EFFECTIVE_QUOTA) -> None:
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="pro",
            tier="pro",
            quota_bytes=quota_bytes,
            trust_multiplier_at_allocation=2.0,
        )
    )


# ---------------------------------------------------------------------------
# /billing/usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_reports_user_plan_quota(client, db_session):
    _seed_plan(db_session)
    await db_session.commit()

    resp = await client.get("/api/v1/billing/usage", headers=AUTH)
    assert resp.status_code == 200
    quota = resp.json()["storage"]["quota_bytes"]
    assert quota == EFFECTIVE_QUOTA
    assert quota != settings.default_storage_quota


@pytest.mark.asyncio
async def test_usage_no_plan_row_falls_back_to_default(client):
    resp = await client.get("/api/v1/billing/usage", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["storage"]["quota_bytes"] == settings.default_storage_quota


# ---------------------------------------------------------------------------
# /billing/summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_reports_user_plan_quota_and_percent(client, db_session):
    from api.app.routes.billing import _format_bytes

    _seed_plan(db_session)
    db_session.add(
        FileRecord(
            id="f-quota-sum",
            identity_id="test-user-001",
            product="general",
            file_type="file",
            filename="s.bin",
            storage_key="k-quota-sum",
            size_bytes=2_147_483_648,  # 2 GB
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/billing/summary", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["storage_quota"] == _format_bytes(EFFECTIVE_QUOTA)
    assert body["storage_quota"] != _format_bytes(settings.default_storage_quota)
    # Percent must be computed against the REAL quota: 2 GB / 200 GB = 1%.
    # (Against the old 5 GB default it would have shown 40%.)
    assert body["storage_percent"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_summary_no_plan_row_falls_back_to_default(client):
    from api.app.routes.billing import _format_bytes

    resp = await client.get("/api/v1/billing/summary", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["storage_quota"] == _format_bytes(settings.default_storage_quota)


# ---------------------------------------------------------------------------
# /billing/plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_reports_effective_quota_not_tier_table(client, db_session):
    from api.app.routes.billing import PLAN_PRICES_CENTS

    _seed_plan(db_session)
    await db_session.commit()

    resp = await client.get("/api/v1/billing/plan", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"] == "pro"
    assert body["name"] == "Pro"
    # The trust-multiplied effective quota — NOT settings.tier_quota_pro.
    assert body["quota_bytes"] == EFFECTIVE_QUOTA
    assert body["quota_bytes"] != settings.tier_quota_pro
    # Tier metadata (name/price) still comes from the tier table.
    assert body["price_cents_per_month"] == PLAN_PRICES_CENTS["pro"]


@pytest.mark.asyncio
async def test_plan_no_plan_row_falls_back_to_default(client):
    resp = await client.get("/api/v1/billing/plan", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"] == "free"
    assert body["quota_bytes"] == settings.default_storage_quota


# ---------------------------------------------------------------------------
# Display == enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_displayed_quota_matches_enforcement_helper(client, db_session):
    """What the user is SHOWN must equal what the upload gate ENFORCES."""
    from api.app.services.quota import get_quota_bytes

    _seed_plan(db_session)
    await db_session.commit()

    enforced = await get_quota_bytes(db_session, identity_id="test-user-001")
    resp = await client.get("/api/v1/billing/usage", headers=AUTH)
    assert resp.status_code == 200
    shown = resp.json()["storage"]["quota_bytes"]
    assert shown == enforced == EFFECTIVE_QUOTA
