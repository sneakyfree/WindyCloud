"""Frozen-account gate: revoked passport → uploads return 403."""

from __future__ import annotations

import json

import pytest

from api.app.db.models import UserPlan


@pytest.mark.asyncio
async def test_upload_blocked_when_plan_frozen(client, db_session):
    # Seed a frozen plan for TEST_USER
    db_session.add(
        UserPlan(
            identity_id="test-user-001",
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
            frozen=True,
        )
    )
    await db_session.commit()

    # require_not_frozen is mocked by conftest for convenience — so hit
    # the production dependency directly by removing the override
    from api.app.auth.webhook import require_not_frozen
    from api.app.main import create_app
    from api.app.auth.dependencies import get_current_user
    from api.app.db.engine import get_db

    app = create_app()

    async def _user():
        from api.app.auth.dependencies import AuthenticatedUser

        return AuthenticatedUser(
            identity_id="test-user-001",
            claims={"sub": "test-user-001"},
            source="windy_pro",
        )

    async def _db():
        yield db_session

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    # Do NOT override require_not_frozen — we want the real one

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/storage/upload",
            files={"file": ("f.bin", b"abc", "application/octet-stream")},
            data={"metadata": json.dumps({})},
            headers={"Authorization": "Bearer fake"},
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "frozen_account"
