"""Auth tests — validate dependency behavior."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected():
    """Requests without auth header should get 403."""
    from api.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/storage/files")
        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_health_no_auth_required():
    """Health endpoint should not require auth."""
    from api.app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_authenticated_request_passes(client):
    """With mocked auth, storage list should return 200."""
    resp = await client.get(
        "/api/v1/storage/files",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200
