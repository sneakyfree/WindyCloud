"""Tests for the billing snapshot background task."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from api.app.db.models import BillingSnapshot
from api.app.tasks.billing_snapshot import take_billing_snapshots


@pytest.mark.asyncio
async def test_billing_snapshot_creates_record(client, db_session):
    """Uploading a file and running snapshots should create a billing snapshot."""
    # Upload a file to create some usage
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("test.txt", b"hello world", "text/plain")},
        data={"product": "general"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200

    # Run the billing snapshot task
    count = await take_billing_snapshots(db_session)
    assert count >= 1

    # Verify a snapshot was created
    result = await db_session.execute(
        select(BillingSnapshot).where(BillingSnapshot.identity_id == "test-user-001")
    )
    snapshot = result.scalar_one_or_none()
    assert snapshot is not None
    assert snapshot.storage_bytes == 11  # len(b"hello world")
    assert snapshot.file_count == 1


@pytest.mark.asyncio
async def test_billing_snapshot_updates_existing(client, db_session):
    """Running snapshots twice on the same day should update, not duplicate."""
    # Upload a file
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("a.txt", b"aaa", "text/plain")},
        data={"product": "general"},
        headers={"Authorization": "Bearer fake"},
    )

    # Run twice
    await take_billing_snapshots(db_session)
    await take_billing_snapshots(db_session)

    # Should have exactly one snapshot for today
    result = await db_session.execute(
        select(BillingSnapshot).where(BillingSnapshot.identity_id == "test-user-001")
    )
    snapshots = result.scalars().all()
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_billing_snapshot_empty_db(db_session):
    """No identities means zero snapshots."""
    count = await take_billing_snapshots(db_session)
    assert count == 0
