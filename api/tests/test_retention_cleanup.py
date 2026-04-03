"""Tests for retention_days cleanup task."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from api.app.db.models import FileRecord
from api.app.tasks.retention_cleanup import enforce_retention_days


@pytest.mark.asyncio
async def test_retention_days_deletes_expired(db_session):
    """Files past their retention_days should be deleted."""
    now = datetime.now(timezone.utc)

    # Create an expired file (retention_days=1, created 3 days ago)
    expired = FileRecord(
        id="expired-001",
        identity_id="test-user-001",
        product="windy_mail",
        file_type="mail_backup",
        filename="old_backup.gz",
        storage_key="test-user-001/windy_mail/mail_backup/old_backup.gz",
        size_bytes=1024,
        retention_days=1,
        created_at=now - timedelta(days=3),
    )
    db_session.add(expired)

    # Create a non-expired file (retention_days=30, created 1 day ago)
    fresh = FileRecord(
        id="fresh-001",
        identity_id="test-user-001",
        product="windy_mail",
        file_type="mail_backup",
        filename="new_backup.gz",
        storage_key="test-user-001/windy_mail/mail_backup/new_backup.gz",
        size_bytes=2048,
        retention_days=30,
        created_at=now - timedelta(days=1),
    )
    db_session.add(fresh)
    await db_session.commit()

    deleted = await enforce_retention_days(db_session)
    assert deleted == 1

    # Expired file should be gone
    result = await db_session.execute(select(FileRecord).where(FileRecord.id == "expired-001"))
    assert result.scalar_one_or_none() is None

    # Fresh file should still exist
    result = await db_session.execute(select(FileRecord).where(FileRecord.id == "fresh-001"))
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_retention_days_ignores_null(db_session):
    """Files without retention_days should not be deleted."""
    now = datetime.now(timezone.utc)

    no_retention = FileRecord(
        id="no-ret-001",
        identity_id="test-user-001",
        product="general",
        file_type="file",
        filename="permanent.txt",
        storage_key="test-user-001/general/file/permanent.txt",
        size_bytes=512,
        retention_days=None,
        created_at=now - timedelta(days=365),
    )
    db_session.add(no_retention)
    await db_session.commit()

    deleted = await enforce_retention_days(db_session)
    assert deleted == 0


@pytest.mark.asyncio
async def test_retention_days_empty_db(db_session):
    """No files means zero deletions."""
    deleted = await enforce_retention_days(db_session)
    assert deleted == 0
