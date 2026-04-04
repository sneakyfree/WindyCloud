"""Utility to add X-Storage-Warning headers to responses."""

from __future__ import annotations

from fastapi import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.config import settings
from api.app.db.models import FileRecord


async def add_storage_warning(response: Response, identity_id: str, db: AsyncSession) -> None:
    """Add X-Storage-Warning header if user is approaching quota.

    Call this from storage/archive route handlers.
    """
    result = await db.execute(
        select(func.coalesce(func.sum(FileRecord.size_bytes), 0)).where(
            FileRecord.identity_id == identity_id
        )
    )
    used = result.scalar() or 0
    quota = settings.default_storage_quota
    pct = (used / quota * 100) if quota > 0 else 0

    if pct >= 100:
        response.headers["X-Storage-Warning"] = "quota_exceeded"
        response.headers["X-Storage-Used-Percent"] = "100"
    elif pct >= 95:
        response.headers["X-Storage-Warning"] = "critical"
        response.headers["X-Storage-Used-Percent"] = str(round(pct))
    elif pct >= 80:
        response.headers["X-Storage-Warning"] = "approaching"
        response.headers["X-Storage-Used-Percent"] = str(round(pct))
