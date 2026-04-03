"""Quota and upload size limit tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upload_exceeds_max_size(client):
    """Files exceeding max upload size should return 413."""
    from api.app.config import settings

    original = settings.max_upload_size
    settings.max_upload_size = 100  # 100 bytes

    try:
        resp = await client.post(
            "/api/v1/storage/upload",
            files={"file": ("big.bin", b"x" * 200, "application/octet-stream")},
            headers={"Authorization": "Bearer fake"},
        )
        assert resp.status_code == 413
        assert "exceeds maximum size" in resp.json()["detail"]
    finally:
        settings.max_upload_size = original


@pytest.mark.asyncio
async def test_upload_exceeds_quota(client):
    """Uploads exceeding storage quota should return 507."""
    from api.app.config import settings

    original = settings.default_storage_quota
    settings.default_storage_quota = 50  # 50 bytes

    try:
        # First upload fills the quota
        resp = await client.post(
            "/api/v1/storage/upload",
            files={"file": ("a.txt", b"x" * 40, "text/plain")},
            headers={"Authorization": "Bearer fake"},
        )
        assert resp.status_code == 200

        # Second upload exceeds quota
        resp = await client.post(
            "/api/v1/storage/upload",
            files={"file": ("b.txt", b"x" * 20, "text/plain")},
            headers={"Authorization": "Bearer fake"},
        )
        assert resp.status_code == 507
        assert "quota exceeded" in resp.json()["detail"].lower()
    finally:
        settings.default_storage_quota = original


@pytest.mark.asyncio
async def test_upload_within_quota_succeeds(client):
    """Uploads within quota should succeed."""
    from api.app.config import settings

    original = settings.default_storage_quota
    settings.default_storage_quota = 1000

    try:
        resp = await client.post(
            "/api/v1/storage/upload",
            files={"file": ("ok.txt", b"small file", "text/plain")},
            headers={"Authorization": "Bearer fake"},
        )
        assert resp.status_code == 200
    finally:
        settings.default_storage_quota = original


@pytest.mark.asyncio
async def test_invalid_metadata_json(client):
    """Invalid JSON in metadata should return 400."""
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
        data={"metadata": "not valid json {{{"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
    assert "Invalid JSON" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_storage_health_no_auth(client):
    """Storage health should work without authentication."""
    resp = await client.get("/api/v1/storage/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_status_reflects_mock_providers(client):
    """Status endpoint should show mock providers when enabled."""
    resp = await client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pillars"]["storage"]["enabled"] is True
    assert body["pillars"]["storage"]["provider"] == "local_disk"
    assert body["pillars"]["compute"]["enabled"] is True
    assert body["pillars"]["compute"]["provider"] == "mock"
    assert body["pillars"]["servers"]["enabled"] is True
    assert body["pillars"]["servers"]["provider"] == "mock"
