"""Retention cleanup — deletes archived files older than their retention_days."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.db.models import FileRecord

logger = logging.getLogger(__name__)


async def enforce_retention_days(db: AsyncSession) -> int:
    """Delete files that have exceeded their retention_days.

    Only applies to files with a non-null retention_days value.
    Returns the number of files deleted.
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(select(FileRecord).where(FileRecord.retention_days.isnot(None)))
    records = result.scalars().all()

    deleted = 0
    for record in records:
        if not record.retention_days or record.retention_days <= 0:
            continue
        cutoff = record.created_at + timedelta(days=record.retention_days)
        if now > cutoff:
            logger.info(
                "Deleting expired file %s (created %s, retention %d days)",
                record.id,
                record.created_at,
                record.retention_days,
            )
            # Delete from storage provider
            try:
                from api.app.config import settings

                if settings.r2_configured:
                    from api.app.providers.r2 import R2StorageProvider

                    provider = R2StorageProvider()
                else:
                    from api.app.providers.local_disk import LocalDiskProvider

                    provider = LocalDiskProvider()
                await provider.delete(record.storage_key)
            except Exception:
                logger.exception("Failed to delete storage for %s", record.storage_key)

            await db.delete(record)
            deleted += 1

    if deleted:
        await db.commit()
        logger.info("Retention cleanup: deleted %d expired files", deleted)

    return deleted
