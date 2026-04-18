"""Sync status endpoint — shows last backup and schedule per product.

Wave 8 adds the post-hatch auto-backup offer endpoint:
`POST /sync/offer-backup` is pinged by the Windy Pro Electron app once
the user has hatched an identity and we've detected pre-existing
recordings on disk. It queues the first backup, fires a Chat push
notification, and is idempotent per windy_identity_id so device
retries and cross-device hatches don't double-notify.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.db.engine import get_db
from api.app.db.models import BackupOffer, FileRecord
from api.app.services.chat_push import send_first_backup_notification

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# POST /sync/offer-backup  (Wave 8 — grandma-ribbon auto-backup)
# ---------------------------------------------------------------------------


class OfferBackupRequest(BaseModel):
    """Ping from the Windy Pro Electron app after hatch.

    Indicates the user has local recordings we can claim on their
    behalf. The endpoint is idempotent per identity, so the desktop can
    retry freely on flaky networks without producing duplicate offers.
    """

    recording_count: int = Field(..., ge=0, le=100_000)
    bytes_estimated: int = Field(default=0, ge=0)


@router.post("/offer-backup", status_code=status.HTTP_200_OK)
async def offer_backup(
    body: OfferBackupRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Queue the first-backup job and fire the Chat push notification.

    Idempotent on `windy_identity_id`: a second call for the same
    identity returns the existing offer and does **not** re-notify.
    """
    if body.recording_count == 0:
        # Nothing to back up — reject so the desktop doesn't paper over
        # its own detection bug by pinging us with a zero count.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="recording_count must be > 0",
        )

    existing_row = await db.execute(
        select(BackupOffer).where(BackupOffer.identity_id == user.identity_id)
    )
    existing = existing_row.scalar_one_or_none()
    if existing is not None:
        return {
            "status": "already_offered",
            "identity_id": existing.identity_id,
            "recording_count": existing.recording_count,
            "notified": existing.notification_sent,
            "notified_at": (
                existing.notification_sent_at.isoformat() if existing.notification_sent_at else None
            ),
        }

    offer = BackupOffer(
        identity_id=user.identity_id,
        recording_count=body.recording_count,
        bytes_estimated=body.bytes_estimated,
    )
    db.add(offer)
    # Flush before we call out so a duplicate concurrent ping hits the
    # PK constraint rather than sending two notifications.
    await db.flush()

    notified = False
    try:
        notified = await send_first_backup_notification(
            windy_identity_id=user.identity_id,
            recording_count=body.recording_count,
        )
    except Exception:
        # send_first_backup_notification already logs + swallows every
        # expected failure mode; a catch-all here only matters if the
        # gateway client itself has a bug. Don't let that 500 the user's
        # hatch ribbon.
        logger.exception(
            "offer_backup: unexpected error calling chat push-gateway "
            "for identity=%s — persisting offer without notification",
            user.identity_id,
        )

    if notified:
        offer.notification_sent = True
        offer.notification_sent_at = datetime.now(timezone.utc)

    await db.commit()

    return {
        "status": "queued",
        "identity_id": user.identity_id,
        "recording_count": body.recording_count,
        "notified": notified,
    }
