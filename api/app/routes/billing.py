"""Billing endpoints — usage summary, history, estimates."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import BillingSnapshot, ComputeUsageRecord, FileRecord
from api.app.models.billing import (
    BillingEstimateResponse,
    BillingHistoryEntry,
    BillingHistoryResponse,
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
