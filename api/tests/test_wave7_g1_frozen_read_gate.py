"""GAP G1: frozen users cannot list, download, delete, or export either.

Wave 2's freeze only blocked POST /storage/upload and POST /archive/*.
This test exercises every previously-ungated route against a frozen
UserPlan and asserts 403 frozen_account.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from api.app.db.models import FileRecord, UserPlan


@pytest.fixture
async def frozen_client(db_session):
    """Stand up the real app with a real require_not_frozen dep.

    The shared `client` fixture in conftest overrides require_not_frozen
    to always return TEST_USER (non-frozen) so existing tests stay simple.
    Here we need the real gate, so we build a dedicated client.
    """
    from api.app.auth.dependencies import AuthenticatedUser, get_current_user
    from api.app.db.engine import get_db
    from api.app.main import create_app

    identity = "frozen-test-user"

    db_session.add(
        UserPlan(
            identity_id=identity,
            plan_id="pro",
            tier="pro",
            quota_bytes=107_374_182_400,
            frozen=True,
        )
    )
    db_session.add(
        FileRecord(
            id="frz-file-1",
            identity_id=identity,
            product="general",
            file_type="file",
            filename="secret.txt",
            storage_key=f"{identity}/general/file/secret.txt",
            size_bytes=10,
            content_type="text/plain",
        )
    )
    await db_session.commit()

    app = create_app()

    async def _user():
        return AuthenticatedUser(
            identity_id=identity,
            claims={"sub": identity, "windy_identity_id": identity},
            source="windy_pro",
        )

    async def _db():
        yield db_session

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    # IMPORTANT: do NOT override require_not_frozen — we want the real gate.

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


READ_ROUTES = [
    ("GET", "/api/v1/storage/files"),
    ("GET", "/api/v1/storage/files/frz-file-1"),
    ("GET", "/api/v1/storage/usage"),
    ("GET", "/api/v1/storage/breakdown"),
    ("GET", "/api/v1/storage/export"),
    ("DELETE", "/api/v1/storage/files/frz-file-1"),
    ("GET", "/api/v1/archive/retrieve/general/secret.txt"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", READ_ROUTES)
async def test_frozen_user_blocked_on_read(frozen_client, method, path):
    headers = {"Authorization": "Bearer x"}
    resp = await frozen_client.request(method, path, headers=headers)
    assert resp.status_code == 403, (
        f"{method} {path} should 403 frozen_account for a frozen user "
        f"(got {resp.status_code}: {resp.text[:120]})"
    )
    assert resp.json().get("detail") == "frozen_account"


@pytest.mark.asyncio
async def test_frozen_user_blocked_on_upload(frozen_client):
    resp = await frozen_client.post(
        "/api/v1/storage/upload",
        files={"file": ("x.txt", b"hi", "text/plain")},
        data={"metadata": json.dumps({})},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "frozen_account"
