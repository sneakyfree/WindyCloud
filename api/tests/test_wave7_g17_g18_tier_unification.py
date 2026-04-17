"""GAP G17+G18: one tier vocabulary across billing + storage.

Before this fix:
  - routes/billing.PLAN_TIERS       = free/basic/pro/ultra (500MB/5GB/50GB/200GB)
  - routes/billing._tier_quotas()   = free/pro/ultra/max   (5GB/100GB/1TB/5TB)
  - routes/storage.STORAGE_PLANS    = free/basic/pro/ultra (500MB/5GB/50GB/200GB)
  - config.default_storage_quota    = 500 MB
  - config.tier_quota_free          = 5 GB

Every tier lived under two or three names with two or three different
quotas. /billing/plan/upgrade accepted "basic" but /billing/allocate
accepted "max" and rejected "basic". Uploads for users without a
UserPlan row read the 500 MB default; users with a /billing/allocate
"free" plan got 5 GB; users upgraded to "basic" got 5 GB. All three
paths should have been the same number.

After: exactly one vocab, sourced from settings. One price table.
One quota table.
"""

from __future__ import annotations

import pytest


def test_plan_tiers_vocabulary_is_wave2_canonical():
    """PLAN_TIERS keys must be the Wave 2 set — no 'basic' anymore."""
    from api.app.routes.billing import PLAN_TIERS, _tier_quotas

    assert set(PLAN_TIERS.keys()) == {"free", "pro", "ultra", "max"}
    # Same key set as the authoritative quota map.
    assert set(PLAN_TIERS.keys()) == set(_tier_quotas().keys())


def test_plan_tier_quotas_match_settings_tier_quotas():
    from api.app.routes.billing import PLAN_TIERS, _tier_quotas

    quotas = _tier_quotas()
    for tier, meta in PLAN_TIERS.items():
        assert meta["quota_bytes"] == quotas[tier], (
            f"{tier}: PLAN_TIERS says {meta['quota_bytes']}, "
            f"_tier_quotas says {quotas[tier]}"
        )


def test_storage_plans_match_billing_plan_tiers():
    from api.app.routes.billing import PLAN_TIERS
    from api.app.routes.storage import _storage_plans

    plans_by_id = {p.plan_id: p for p in _storage_plans()}
    assert set(plans_by_id.keys()) == set(PLAN_TIERS.keys())

    for tier, meta in PLAN_TIERS.items():
        plan = plans_by_id[tier]
        assert plan.storage_bytes == meta["quota_bytes"], (
            f"{tier}: /storage/plans says {plan.storage_bytes}, "
            f"billing.PLAN_TIERS says {meta['quota_bytes']}"
        )
        assert plan.price_cents_per_month == meta["price_cents"]


def test_default_storage_quota_tracks_free_tier():
    """G18: the un-provisioned-user fallback must equal the free tier."""
    from api.app.config import settings

    assert settings.default_storage_quota == settings.tier_quota_free


@pytest.mark.asyncio
async def test_upgrade_to_max_tier_accepted(client):
    """/billing/plan/upgrade now accepts 'max' (pre-fix it 400'd)."""
    resp = await client.post(
        "/api/v1/billing/plan/upgrade",
        json={"plan_id": "max"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan_id"] == "max"
    assert body["quota_bytes"] == 5_497_558_138_880  # 5 TB


@pytest.mark.asyncio
async def test_upgrade_to_basic_rejected(client):
    """'basic' is no longer a valid tier — an upgrade call to it 400s."""
    resp = await client.post(
        "/api/v1/billing/plan/upgrade",
        json={"plan_id": "basic"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
    assert "basic" in resp.text


def test_price_for_usage_picks_smallest_fit():
    from api.app.routes.billing import PLAN_PRICES_CENTS, _price_cents_for_usage

    # 1 GB fits in free (5 GB) → free price
    assert _price_cents_for_usage(1 * 1024**3) == PLAN_PRICES_CENTS["free"]
    # 50 GB fits in pro (100 GB) → pro price
    assert _price_cents_for_usage(50 * 1024**3) == PLAN_PRICES_CENTS["pro"]
    # 500 GB fits in ultra (1 TB) → ultra price
    assert _price_cents_for_usage(500 * 1024**3) == PLAN_PRICES_CENTS["ultra"]
    # 2 TB fits in max (5 TB) → max price
    assert _price_cents_for_usage(2 * 1024**4) == PLAN_PRICES_CENTS["max"]
    # Over 5 TB still bills max (over-quota is an upload-gate concern)
    assert _price_cents_for_usage(10 * 1024**4) == PLAN_PRICES_CENTS["max"]
