"""Wave 12 C-1 — /archive/* now honours UserPlan.quota_bytes.

Pre-Wave-12 every /archive/* endpoint skipped the quota check, so a
service-token caller (agent / mail / word / code / fly backups) could
push past a user's paid-for plan. The Wave 11 hardening report flagged
this as Critical; this test pins the fixed behaviour.
"""

from __future__ import annotations

import pytest

from api.app.db.models import UserPlan


@pytest.mark.asyncio
async def test_archive_chat_rejects_past_quota(client, db_session):
    """2 KB archive upload against a 1 KB plan quota must 507."""
    # Allocate a tiny plan for the test user.
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="free",
            tier="free",
            quota_bytes=1024,
            frozen=False,
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("oversize.bin", b"x" * 2048, "application/octet-stream")},
        data={"metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 507, resp.text
    assert "quota" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_archive_chat_accepts_under_quota(client, db_session):
    """Same tiny plan, but a 512-byte upload fits: must succeed."""
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="free",
            tier="free",
            quota_bytes=1024,
            frozen=False,
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("small.bin", b"x" * 512, "application/octet-stream")},
        data={"metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_archive_chat_running_total_blocks_second_upload(client, db_session):
    """First 600 B fits; second 600 B would push 1200 B > 1024 B quota."""
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="free",
            tier="free",
            quota_bytes=1024,
            frozen=False,
        )
    )
    await db_session.commit()

    r1 = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("a.bin", b"a" * 600, "application/octet-stream")},
        data={"metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("b.bin", b"b" * 600, "application/octet-stream")},
        data={"metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert r2.status_code == 507, r2.text


@pytest.mark.asyncio
async def test_archive_mail_also_gated(client, db_session):
    """The fix lives in the shared _do_archive_upload helper, so every
    /archive/* endpoint — not just /chat — inherits the check."""
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="free",
            tier="free",
            quota_bytes=1024,
            frozen=False,
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/archive/mail",
        files={"file": ("big.eml", b"y" * 2048, "application/octet-stream")},
        data={"metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 507, resp.text


@pytest.mark.asyncio
async def test_storage_upload_still_gated(client, db_session):
    """Regression guard — the /storage/upload quota gate still fires
    after being refactored to call the shared helper."""
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="free",
            tier="free",
            quota_bytes=1024,
            frozen=False,
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("big.bin", b"z" * 2048, "application/octet-stream")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 507, resp.text
