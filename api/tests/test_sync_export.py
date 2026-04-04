"""Tests for sync status, background export, and storage warnings."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_sync_status_empty(client):
    """Sync status with no files shows all products with Never."""
    resp = await client.get(
        "/api/v1/sync/status",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    products = resp.json()["products"]
    assert len(products) == 5
    labels = {p["label"] for p in products}
    assert "Windy Chat" in labels
    assert "Windy Mail" in labels
    assert "Windy Fly" in labels
    for p in products:
        assert p["last_backup"] == "Never"
        assert p["health"] in ("green", "gray")


@pytest.mark.asyncio
async def test_sync_status_with_files(client):
    """Uploading a file updates sync status for that product."""
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("backup.enc", b"encrypted", "application/octet-stream")},
        data={"product": "windy_chat"},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/sync/status",
        headers={"Authorization": "Bearer fake"},
    )
    products = {p["product"]: p for p in resp.json()["products"]}
    chat = products["windy_chat"]
    assert chat["last_backup"] != "Never"
    assert chat["file_count"] == 1
    assert chat["bytes_synced"] > 0
    assert chat["health"] == "green"


@pytest.mark.asyncio
async def test_export_request(client):
    """POST /api/v1/export/my-data returns a job."""
    resp = await client.post(
        "/api/v1/export/my-data",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body["status"] in ("pending", "processing", "completed")


@pytest.mark.asyncio
async def test_export_status(client):
    """Can poll export job status."""
    resp = await client.post(
        "/api/v1/export/my-data",
        headers={"Authorization": "Bearer fake"},
    )
    job_id = resp.json()["job_id"]

    resp = await client.get(
        f"/api/v1/export/{job_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id


@pytest.mark.asyncio
async def test_export_not_found(client):
    """Unknown job_id returns 404."""
    resp = await client.get(
        "/api/v1/export/nonexistent-id",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_storage_warning_header(client):
    """Usage endpoint includes X-Storage-Warning when near quota."""
    from api.app.config import settings

    original_quota = settings.default_storage_quota
    # Set tiny quota so we trigger warning
    settings.default_storage_quota = 100

    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("f.txt", b"x" * 85, "text/plain")},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/storage/usage",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("x-storage-warning") in ("approaching", "critical")

    settings.default_storage_quota = original_quota


@pytest.mark.asyncio
async def test_upload_blocked_at_quota(client):
    """Upload blocked when quota exceeded."""
    from api.app.config import settings

    original_quota = settings.default_storage_quota
    settings.default_storage_quota = 10

    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("big.bin", b"x" * 20, "application/octet-stream")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 507
    assert "Upgrade" in resp.json()["detail"]

    settings.default_storage_quota = original_quota
