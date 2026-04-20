"""Analytics endpoints — daily metrics for admin dashboard.

Wave 14 P1: gated on `require_admin`. The smoke report flagged that
pre-Wave-14 these endpoints returned fleet-wide aggregate metrics
(`total_files_uploaded`, `total_storage_bytes`, `compute_minutes`, …)
to any authenticated user. Not PII per se, but business metrics a
competitor or churned free user shouldn't trivially scrape, and the
surface becomes a business-health leak at scale. See
`docs/SMOKE_REPORT_2026-04-19.md §8`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, require_admin
from api.app.db.engine import get_db
from api.app.db.models import AnalyticsEvent

router = APIRouter()


@router.get("/daily")
async def daily_analytics(
    days: int = Query(30, ge=1, le=365),
    user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get daily analytics for the last N days."""
    result = await db.execute(
        select(AnalyticsEvent).order_by(AnalyticsEvent.date.desc()).limit(days * 10)
    )
    events = result.scalars().all()

    # Group by date
    by_date: dict[str, dict] = {}
    for e in events:
        if e.date not in by_date:
            by_date[e.date] = {
                "date": e.date,
                "files_uploaded": 0,
                "storage_growth_bytes": 0,
                "compute_minutes": 0,
                "archive_operations": 0,
            }
        day = by_date[e.date]
        if e.event_type == "file_upload":
            day["files_uploaded"] += e.count
            day["storage_growth_bytes"] += e.value
        elif e.event_type == "compute_stt":
            day["compute_minutes"] += round(e.value / 60, 2)
        elif e.event_type == "archive":
            day["archive_operations"] += e.count

    return {
        "days": sorted(by_date.values(), key=lambda d: d["date"], reverse=True),
    }


@router.get("/summary")
async def analytics_summary(
    user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Overall analytics summary."""
    result = await db.execute(select(AnalyticsEvent))
    events = result.scalars().all()

    total_uploads = 0
    total_bytes = 0
    total_compute_seconds = 0
    total_archives = 0
    archives_by_product: dict[str, int] = {}

    for e in events:
        if e.event_type == "file_upload":
            total_uploads += e.count
            total_bytes += e.value
        elif e.event_type == "compute_stt":
            total_compute_seconds += e.value
        elif e.event_type == "archive":
            total_archives += e.count
            if e.product:
                archives_by_product[e.product] = archives_by_product.get(e.product, 0) + e.count

    return {
        "total_files_uploaded": total_uploads,
        "total_storage_bytes": total_bytes,
        "total_compute_minutes": round(total_compute_seconds / 60, 2),
        "total_archive_operations": total_archives,
        "archives_by_product": archives_by_product,
    }
