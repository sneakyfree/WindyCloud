"""Cold storage migration and retrieval tests."""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_migrate_registers_files(client):
    """POST /api/v1/archive/migrate registers file metadata in cold storage."""
    resp = await client.post(
        "/api/v1/archive/migrate",
        json={
            "product": "windy_chat",
            "windy_identity_id": "test-user-001",
            "files": [
                {
                    "filename": "backup_2026-04-01.enc",
                    "size": 4096,
                    "content_type": "application/octet-stream",
                    "encrypted": True,
                    "retention_days": 90,
                },
                {
                    "filename": "backup_2026-04-02.enc",
                    "size": 8192,
                    "content_type": "application/octet-stream",
                    "encrypted": True,
                },
            ],
        },
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["product"] == "windy_chat"
    assert body["identity_id"] == "test-user-001"
    assert body["migrated"] == 2
    assert len(body["results"]) == 2
    assert body["results"][0]["status"] == "migrated"
    assert "windy_chat" in body["results"][0]["key"]


@pytest.mark.asyncio
async def test_migrate_idempotent(client):
    """Migrating the same file twice returns already_exists."""
    payload = {
        "product": "windy_mail",
        "windy_identity_id": "test-user-001",
        "files": [{"filename": "pg_dump.sql.gz", "size": 1024}],
    }

    # First migration
    resp = await client.post(
        "/api/v1/archive/migrate",
        json=payload,
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "migrated"

    # Second migration — same file
    resp = await client.post(
        "/api/v1/archive/migrate",
        json=payload,
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "already_exists"
    assert resp.json()["migrated"] == 0


@pytest.mark.asyncio
async def test_migrate_invalid_product(client):
    """Unknown product returns 400."""
    resp = await client.post(
        "/api/v1/archive/migrate",
        json={
            "product": "nonexistent_product",
            "windy_identity_id": "test-user-001",
            "files": [{"filename": "test.bin", "size": 100}],
        },
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_retrieve_uploaded_file(client):
    """Upload a file via archive, then retrieve it."""
    # Upload via archive endpoint
    resp = await client.post(
        "/api/v1/archive/agent",
        files={"file": ("agent.db", b"sqlite-backup-data", "application/x-sqlite3")},
        data={"metadata": json.dumps({"agent_name": "Aria"})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    filename = "agent.db"

    # Retrieve from cold storage
    resp = await client.get(
        f"/api/v1/archive/retrieve/windy_fly/{filename}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.content == b"sqlite-backup-data"


@pytest.mark.asyncio
async def test_retrieve_not_found(client):
    """Retrieving nonexistent file returns 404."""
    resp = await client.get(
        "/api/v1/archive/retrieve/windy_chat/nonexistent.enc",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404
