"""Shared storage-quota check.

Pre-Wave-12 the quota math lived only in `routes/storage.py::upload_file`.
`routes/archive.py::_do_archive_upload` — the path every Windy product
uses for service-to-service backups (windy-chat, windy-mail, windy-fly,
windy-word, windy-code) — skipped the check entirely. Wave 11 hardening
flagged this as C-1: an upstream bug in any of those products could
silently push past a user's paid-for quota.

This module is the single source of truth. Both callers share it. If
you're adding a third upload path, call `check_quota` before writing
to storage.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.config import settings
from api.app.db.models import FileRecord, UserPlan


class QuotaExceeded(HTTPException):
    """507 Insufficient Storage. Separate subclass so routes + middlewares
    can match it without brittle string comparisons."""

    def __init__(self, current_usage: int, additional: int, quota: int) -> None:
        super().__init__(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="Storage quota exceeded. Upgrade your plan for more space.",
        )
        self.current_usage = current_usage
        self.additional = additional
        self.quota = quota


async def check_quota(
    db: AsyncSession,
    *,
    identity_id: str,
    additional_bytes: int,
) -> int:
    """Raise 507 if `current_usage + additional_bytes` would exceed the
    identity's plan quota. Return the identity's current usage on success.

    Reads UserPlan.quota_bytes when a plan row exists, otherwise the
    global `settings.default_storage_quota`. Uses a single
    `SUM(FileRecord.size_bytes)` rollup rather than tracking a counter
    column — the eventual-consistency window is narrow because we commit
    inside the same request, and there's no schema churn if FileRecord
    gains / loses fields.
    """
    plan_row = await db.execute(select(UserPlan).where(UserPlan.identity_id == identity_id))
    plan = plan_row.scalar_one_or_none()
    quota = plan.quota_bytes if plan else settings.default_storage_quota

    usage_row = await db.execute(
        select(func.coalesce(func.sum(FileRecord.size_bytes), 0)).where(
            FileRecord.identity_id == identity_id
        )
    )
    current_usage = int(usage_row.scalar() or 0)

    if current_usage + additional_bytes > quota:
        raise QuotaExceeded(
            current_usage=current_usage,
            additional=additional_bytes,
            quota=quota,
        )
    return current_usage
