"""Sync status endpoint — shows last backup and schedule per product."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.db.engine import get_db
from api.app.db.models import FileRecord

router = APIRouter()

# Sync schedules per product (hardcoded — products push to us on their own schedule)
SYNC_SCHEDULES = {
    "windy_chat": {
        "label": "Windy Chat",
        "schedule": "Encrypted backup every 24 hours",
        "interval_hours": 24,
    },
    "windy_mail": {
        "label": "Windy Mail",
        "schedule": "Auto-archive emails older than 90 days",
        "interval_hours": 24,
    },
    "windy_fly": {
        "label": "Windy Fly",
        "schedule": "Database backup daily at 3am",
        "interval_hours": 24,
    },
    "windy_pro": {
        "label": "Windy Word",
        "schedule": "Recordings sync on save",
        "interval_hours": 0,  # event-driven, no fixed interval
    },
    "windy_code": {
        "label": "Windy Code",
        "schedule": "Settings sync on change",
        "interval_hours": 0,
    },
}


def _time_ago(dt: datetime) -> str:
    """Human-readable time difference."""
    now = datetime.now(timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = seconds // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _time_until(dt: datetime) -> str:
    """Human-readable time until."""
    now = datetime.now(timezone.utc)
    diff = dt - now
    seconds = int(diff.total_seconds())
    if seconds <= 0:
        return "overdue"
    if seconds < 3600:
        m = seconds // 60
        return f"in {m} minute{'s' if m != 1 else ''}"
    if seconds < 86400:
        h = seconds // 3600
        return f"in {h} hour{'s' if h != 1 else ''}"
    d = seconds // 86400
    return f"in {d} day{'s' if d != 1 else ''}"


def _sync_health(last: datetime | None, interval_hours: int) -> str:
    """green / yellow / red based on how overdue the sync is."""
    if last is None:
        return "gray"  # never synced
    if interval_hours == 0:
        return "green"  # event-driven, no schedule
    now = datetime.now(timezone.utc)
    overdue = now - last - timedelta(hours=interval_hours)
    if overdue.total_seconds() < 0:
        return "green"
    if overdue.total_seconds() < interval_hours * 3600:
        return "yellow"  # up to 1 interval overdue
    return "red"


@router.get("/status")
async def sync_status(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-product sync status with last backup time and health color."""
    # Get latest file per product
    result = await db.execute(
        select(
            FileRecord.product,
            func.max(FileRecord.created_at),
            func.coalesce(func.sum(FileRecord.size_bytes), 0),
            func.count(FileRecord.id),
        )
        .where(FileRecord.identity_id == user.identity_id)
        .group_by(FileRecord.product)
    )
    by_product: dict[str, dict] = {}
    for product, last_at, total_bytes, count in result.all():
        by_product[product] = {
            "last_backup_at": last_at.isoformat() if last_at else None,
            "bytes_synced": total_bytes,
            "file_count": count,
        }

    products = []
    for product, config in SYNC_SCHEDULES.items():
        data = by_product.get(product, {})
        last_at_str = data.get("last_backup_at")
        last_at = None
        if last_at_str:
            last_at = datetime.fromisoformat(last_at_str)
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
        interval = config["interval_hours"]

        next_backup = None
        next_backup_str = None
        if last_at and interval > 0:
            next_backup = last_at + timedelta(hours=interval)
            next_backup_str = _time_until(next_backup)
        elif interval == 0:
            next_backup_str = "On next change"

        products.append(
            {
                "product": product,
                "label": config["label"],
                "schedule": config["schedule"],
                "last_backup": _time_ago(last_at) if last_at else "Never",
                "last_backup_at": last_at_str,
                "next_backup": next_backup_str,
                "bytes_synced": data.get("bytes_synced", 0),
                "file_count": data.get("file_count", 0),
                "health": _sync_health(last_at, interval),
            }
        )

    return {"products": products}
