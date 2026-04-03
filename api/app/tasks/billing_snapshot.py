"""Billing snapshot — records daily usage per identity for billing history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.db.models import BillingSnapshot, ComputeUsageRecord, FileRecord

logger = logging.getLogger(__name__)


async def take_billing_snapshots(db: AsyncSession) -> int:
    """Snapshot current storage + compute usage for all active identities.

    Returns the number of snapshots created/updated.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get all identities with files
    identity_result = await db.execute(select(distinct(FileRecord.identity_id)))
    identities = [row[0] for row in identity_result.all()]

    # Also include identities with compute usage
    compute_result = await db.execute(
        select(distinct(ComputeUsageRecord.identity_id)).where(ComputeUsageRecord.month == today)
    )
    for row in compute_result.all():
        if row[0] not in identities:
            identities.append(row[0])

    count = 0
    for identity_id in identities:
        # Storage usage
        storage_result = await db.execute(
            select(
                func.coalesce(func.sum(FileRecord.size_bytes), 0),
                func.count(FileRecord.id),
            ).where(FileRecord.identity_id == identity_id)
        )
        storage_row = storage_result.one()

        # Compute usage this month
        compute_row = await db.execute(
            select(ComputeUsageRecord).where(
                ComputeUsageRecord.identity_id == identity_id,
                ComputeUsageRecord.month == today,
            )
        )
        compute_record = compute_row.scalar_one_or_none()

        # Check for existing snapshot today
        existing = await db.execute(
            select(BillingSnapshot).where(
                BillingSnapshot.identity_id == identity_id,
                BillingSnapshot.date == date_str,
            )
        )
        snapshot = existing.scalar_one_or_none()

        if snapshot:
            snapshot.storage_bytes = storage_row[0]
            snapshot.file_count = storage_row[1]
            snapshot.compute_seconds = compute_record.total_seconds if compute_record else 0.0
            snapshot.compute_cost_cents = compute_record.total_cost_cents if compute_record else 0
        else:
            snapshot = BillingSnapshot(
                identity_id=identity_id,
                date=date_str,
                storage_bytes=storage_row[0],
                file_count=storage_row[1],
                compute_seconds=compute_record.total_seconds if compute_record else 0.0,
                compute_cost_cents=(compute_record.total_cost_cents if compute_record else 0),
            )
            db.add(snapshot)
        count += 1

    await db.commit()
    logger.info("Billing snapshots taken for %d identities", count)
    return count
