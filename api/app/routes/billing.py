"""Billing endpoints — usage summary, history, estimates, sync."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.auth.webhook import verify_service_token
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import (
    BillingSnapshot,
    ComputeUsageRecord,
    FileRecord,
    ServerRecord,
    UserPlan,
)
from api.app.models.billing import (
    BillingEstimateResponse,
    BillingHistoryEntry,
    BillingHistoryResponse,
    BillingSummaryResponse,
    BillingSyncRequest,
    BillingSyncResponse,
    BillingUsageResponse,
    ComputeUsageSummary,
    StorageUsageSummary,
)

router = APIRouter()


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@router.get("/usage", response_model=BillingUsageResponse)
async def billing_usage(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    month = _current_month()

    # Storage usage
    storage_result = await db.execute(
        select(
            func.coalesce(func.sum(FileRecord.size_bytes), 0),
            func.count(FileRecord.id),
        ).where(FileRecord.identity_id == user.identity_id)
    )
    storage_row = storage_result.one()

    # Compute usage this month
    compute_result = await db.execute(
        select(ComputeUsageRecord).where(
            ComputeUsageRecord.identity_id == user.identity_id,
            ComputeUsageRecord.month == month,
        )
    )
    compute_record = compute_result.scalar_one_or_none()

    compute_cost = compute_record.total_cost_cents if compute_record else 0

    return BillingUsageResponse(
        identity_id=user.identity_id,
        month=month,
        storage=StorageUsageSummary(
            used_bytes=storage_row[0],
            file_count=storage_row[1],
            quota_bytes=settings.default_storage_quota,
        ),
        compute=ComputeUsageSummary(
            total_seconds=compute_record.total_seconds if compute_record else 0.0,
            total_jobs=compute_record.total_jobs if compute_record else 0,
            total_cost_cents=compute_cost,
        ),
        total_cost_cents=compute_cost,
    )


@router.get("/history", response_model=BillingHistoryResponse)
async def billing_history(
    months: int = Query(6, ge=1, le=24),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Try billing snapshots first
    result = await db.execute(
        select(BillingSnapshot)
        .where(BillingSnapshot.identity_id == user.identity_id)
        .order_by(BillingSnapshot.date.desc())
        .limit(months * 31)
    )
    snapshots = result.scalars().all()

    if snapshots:
        # Group snapshots by month, take the latest per month
        by_month: dict[str, BillingSnapshot] = {}
        for s in snapshots:
            month_key = s.date[:7]  # "2026-04"
            if month_key not in by_month:
                by_month[month_key] = s

        entries = [
            BillingHistoryEntry(
                month=month,
                storage_bytes=snap.storage_bytes,
                compute_seconds=snap.compute_seconds,
                compute_cost_cents=snap.compute_cost_cents,
                total_cost_cents=(
                    snap.compute_cost_cents + _estimate_storage_cost(snap.storage_bytes)
                ),
            )
            for month, snap in sorted(by_month.items(), reverse=True)[:months]
        ]
    else:
        # Fallback to compute_usage records
        cu_result = await db.execute(
            select(ComputeUsageRecord)
            .where(ComputeUsageRecord.identity_id == user.identity_id)
            .order_by(ComputeUsageRecord.month.desc())
            .limit(months)
        )
        records = cu_result.scalars().all()
        entries = [
            BillingHistoryEntry(
                month=r.month,
                storage_bytes=0,
                compute_seconds=r.total_seconds,
                compute_cost_cents=r.total_cost_cents,
                total_cost_cents=r.total_cost_cents,
            )
            for r in records
        ]

    return BillingHistoryResponse(entries=entries)


@router.get("/estimate", response_model=BillingEstimateResponse)
async def billing_estimate(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    month = _current_month()

    # Current compute costs
    compute_result = await db.execute(
        select(ComputeUsageRecord).where(
            ComputeUsageRecord.identity_id == user.identity_id,
            ComputeUsageRecord.month == month,
        )
    )
    compute_record = compute_result.scalar_one_or_none()
    compute_cost = compute_record.total_cost_cents if compute_record else 0

    # Storage cost estimate
    storage_result = await db.execute(
        select(func.coalesce(func.sum(FileRecord.size_bytes), 0)).where(
            FileRecord.identity_id == user.identity_id
        )
    )
    used_bytes = storage_result.scalar() or 0
    storage_cost = _estimate_storage_cost(used_bytes)

    return BillingEstimateResponse(
        month=month,
        storage_cost_cents=storage_cost,
        compute_cost_cents=compute_cost,
        total_estimated_cents=storage_cost + compute_cost,
    )


@router.post("/sync", response_model=BillingSyncResponse)
async def billing_sync(
    body: BillingSyncRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Service-to-service endpoint for Windy Pro to pull usage data for Stripe billing."""
    identity_id = body.windy_identity_id
    month = _current_month()

    # Storage usage
    storage_result = await db.execute(
        select(
            func.coalesce(func.sum(FileRecord.size_bytes), 0),
            func.count(FileRecord.id),
        ).where(FileRecord.identity_id == identity_id)
    )
    storage_row = storage_result.one()

    # Compute usage
    compute_result = await db.execute(
        select(ComputeUsageRecord).where(
            ComputeUsageRecord.identity_id == identity_id,
            ComputeUsageRecord.month == month,
        )
    )
    compute_record = compute_result.scalar_one_or_none()
    compute_seconds = compute_record.total_seconds if compute_record else 0.0
    compute_cost = compute_record.total_cost_cents if compute_record else 0

    # Active servers
    server_result = await db.execute(
        select(
            func.count(ServerRecord.id),
            func.coalesce(func.sum(ServerRecord.monthly_cost_cents), 0),
        ).where(
            ServerRecord.identity_id == identity_id,
            ServerRecord.status != "terminated",
        )
    )
    server_row = server_result.one()

    storage_cost = _estimate_storage_cost(storage_row[0])
    total = storage_cost + compute_cost + server_row[1]

    return BillingSyncResponse(
        identity_id=identity_id,
        month=month,
        storage_bytes=storage_row[0],
        storage_file_count=storage_row[1],
        compute_minutes=round(compute_seconds / 60.0, 2),
        compute_cost_cents=compute_cost,
        server_count=server_row[0],
        server_monthly_cost_cents=server_row[1],
        total_cost_cents=total,
    )


@router.get("/summary", response_model=BillingSummaryResponse)
async def billing_summary(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Agent-friendly usage summary — used by Windy Fly's `storage` command."""
    month = _current_month()

    # Storage
    storage_result = await db.execute(
        select(
            func.coalesce(func.sum(FileRecord.size_bytes), 0),
            func.count(FileRecord.id),
        ).where(FileRecord.identity_id == user.identity_id)
    )
    storage_row = storage_result.one()
    used_bytes = storage_row[0]
    quota = settings.default_storage_quota
    pct = round((used_bytes / quota) * 100, 2) if quota > 0 else 0

    # Compute
    compute_result = await db.execute(
        select(ComputeUsageRecord).where(
            ComputeUsageRecord.identity_id == user.identity_id,
            ComputeUsageRecord.month == month,
        )
    )
    compute_record = compute_result.scalar_one_or_none()
    compute_seconds = compute_record.total_seconds if compute_record else 0.0
    compute_cost = compute_record.total_cost_cents if compute_record else 0
    free_seconds = settings.stt_free_minutes * 60.0
    free_remaining = max(0.0, free_seconds - compute_seconds) / 60.0

    storage_cost = _estimate_storage_cost(used_bytes)

    return BillingSummaryResponse(
        identity_id=user.identity_id,
        storage_used=_format_bytes(used_bytes),
        storage_quota=_format_bytes(quota),
        storage_percent=pct,
        compute_minutes_used=round(compute_seconds / 60.0, 2),
        compute_free_remaining=round(free_remaining, 2),
        total_cost_cents=storage_cost + compute_cost,
    )


def _format_bytes(b: int) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}" if b != int(b) else f"{b} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _estimate_storage_cost(used_bytes: int) -> int:
    """Estimate monthly storage cost in cents based on usage tiers."""
    used_mb = used_bytes / (1024 * 1024)
    if used_mb <= 500:
        return 0
    if used_mb <= 5120:
        return 200  # $2
    if used_mb <= 51200:
        return 500  # $5
    return 1000  # $10


# --- Plan tier definitions ---
def _tier_quotas() -> dict[str, int]:
    """Wave 2 tier quotas — sourced from Settings, not hardcoded."""
    return {
        "free": settings.tier_quota_free,
        "pro": settings.tier_quota_pro,
        "ultra": settings.tier_quota_ultra,
        "max": settings.tier_quota_max,
    }


PLAN_TIERS = {
    "free": {"name": "Free", "quota_bytes": 524_288_000, "price_cents": 0},
    "basic": {"name": "Basic", "quota_bytes": 5_368_709_120, "price_cents": 200},
    "pro": {"name": "Pro", "quota_bytes": 53_687_091_200, "price_cents": 500},
    "ultra": {"name": "Ultra", "quota_bytes": 214_748_364_800, "price_cents": 1000},
}


class AllocateRequest(BaseModel):
    windy_identity_id: str
    passport_number: str | None = None
    tier: str = "free"


class AllocateResponse(BaseModel):
    plan_id: str
    quota_bytes: int
    tier: str
    identity_id: str


async def allocate_plan(
    db: AsyncSession,
    *,
    windy_identity_id: str,
    tier: str,
    passport_number: str | None = None,
) -> UserPlan:
    """Idempotent upsert of a UserPlan for the given identity + tier.

    Trust behavior (Wave 3):
      - If `passport_number` is provided, consult the Eternitas Trust API
        and set effective_quota = base_tier_quota * trust.tier_multiplier.
      - If no passport (human identity via Pro JWT), the multiplier is
        1.0 and the base tier quota applies unchanged.
      - The multiplier in effect at allocation is persisted on the plan
        for audit.

    Raises ValueError if the tier is unknown.
    """
    from api.app.services.trust_client import TrustInfo, get_trust_client

    quotas = _tier_quotas()
    if tier not in quotas:
        raise ValueError(f"Unknown tier: {tier}")
    base_quota = quotas[tier]

    if passport_number:
        trust = await get_trust_client().get_trust(passport_number)
        if trust is None:
            # Passport not found at Eternitas — fail-open to standard
            trust = TrustInfo.default_for_human()
    else:
        trust = TrustInfo.default_for_human()

    multiplier = trust.tier_multiplier
    effective_quota = int(base_quota * multiplier)

    result = await db.execute(
        select(UserPlan).where(UserPlan.identity_id == windy_identity_id)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        plan = UserPlan(
            identity_id=windy_identity_id,
            plan_id=tier,
            tier=tier,
            quota_bytes=effective_quota,
            trust_multiplier_at_allocation=multiplier,
        )
        db.add(plan)
    else:
        plan.plan_id = tier
        plan.tier = tier
        plan.quota_bytes = effective_quota
        plan.trust_multiplier_at_allocation = multiplier
    await db.commit()
    await db.refresh(plan)
    return plan


@router.post(
    "/allocate",
    response_model=AllocateResponse,
    dependencies=[Depends(verify_service_token)],
)
async def billing_allocate(
    body: AllocateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Provision (or refresh) a storage plan for a new identity.

    Called by the identity-created webhook and by windy-agent's hatch
    flow. Idempotent on windy_identity_id.
    """
    from fastapi import HTTPException

    try:
        plan = await allocate_plan(
            db,
            windy_identity_id=body.windy_identity_id,
            tier=body.tier,
            passport_number=body.passport_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AllocateResponse(
        plan_id=plan.plan_id,
        quota_bytes=plan.quota_bytes,
        tier=plan.tier,
        identity_id=plan.identity_id,
    )


@router.get("/plan")
async def get_plan(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user's current storage plan."""
    result = await db.execute(select(UserPlan).where(UserPlan.identity_id == user.identity_id))
    plan = result.scalar_one_or_none()
    plan_id = plan.plan_id if plan else "free"
    tier = PLAN_TIERS.get(plan_id, PLAN_TIERS["free"])
    return {
        "plan_id": plan_id,
        "name": tier["name"],
        "quota_bytes": tier["quota_bytes"],
        "price_cents_per_month": tier["price_cents"],
        "upgrade_url": settings.pricing_url,
    }


@router.post("/plan/upgrade")
async def upgrade_plan(
    body: dict,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upgrade user's storage plan. Called after Stripe payment confirmation."""
    new_plan_id = body.get("plan_id", "")
    if new_plan_id not in PLAN_TIERS:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=f"Unknown plan: {new_plan_id}")

    tier = PLAN_TIERS[new_plan_id]
    result = await db.execute(select(UserPlan).where(UserPlan.identity_id == user.identity_id))
    plan = result.scalar_one_or_none()
    if plan:
        plan.plan_id = new_plan_id
        plan.quota_bytes = tier["quota_bytes"]
    else:
        plan = UserPlan(
            identity_id=user.identity_id,
            plan_id=new_plan_id,
            quota_bytes=tier["quota_bytes"],
        )
        db.add(plan)
    await db.commit()

    return {
        "plan_id": new_plan_id,
        "name": tier["name"],
        "quota_bytes": tier["quota_bytes"],
        "message": f"Plan upgraded to {tier['name']}",
    }
