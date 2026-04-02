"""Archive endpoint tests."""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_archive_chat(client):
    """Chat archive endpoint stores encrypted backup."""
    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("backup.enc", b"encrypted-data", "application/octet-stream")},
        data={"metadata": json.dumps({"encrypted": True, "retention_count": 7})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["product"] == "windy_chat"
    assert body["type"] == "chat_backup"


@pytest.mark.asyncio
async def test_archive_agent(client):
    """Agent archive endpoint stores agent database backup."""
    resp = await client.post(
        "/api/v1/archive/agent",
        files={"file": ("agent.db", b"sqlite-data", "application/x-sqlite3")},
        data={"metadata": json.dumps({"agent_name": "Aria", "passport_id": "EPT-1234"})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["product"] == "windy_fly"
    assert body["type"] == "agent_backup"


@pytest.mark.asyncio
async def test_archive_mail(client):
    resp = await client.post(
        "/api/v1/archive/mail",
        files={"file": ("pg_dump.sql.gz", b"compressed-sql", "application/gzip")},
        data={"metadata": json.dumps({"retention_days": 90})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["product"] == "windy_mail"


@pytest.mark.asyncio
async def test_archive_recordings(client):
    resp = await client.post(
        "/api/v1/archive/recordings",
        files={"file": ("recording.opus", b"audio-data", "audio/opus")},
        data={"metadata": json.dumps({"duration": 120, "format": "opus"})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["product"] == "windy_pro"


@pytest.mark.asyncio
async def test_archive_code_settings(client):
    resp = await client.post(
        "/api/v1/archive/code-settings",
        files={"file": ("settings.json", b'{"theme": "dark"}', "application/json")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["product"] == "windy_code"


@pytest.mark.asyncio
async def test_chat_retention(client):
    """Uploading more than retention_count chat backups should prune oldest."""
    metadata = json.dumps({"encrypted": True, "retention_count": 3})
    for i in range(5):
        resp = await client.post(
            "/api/v1/archive/chat",
            files={"file": (f"backup_{i}.enc", f"data-{i}".encode(), "application/octet-stream")},
            data={"metadata": metadata},
            headers={"Authorization": "Bearer fake"},
        )
        assert resp.status_code == 200

    # List all files — should only have 3 (retention_count)
    resp = await client.get(
        "/api/v1/storage/files?product=windy_chat",
        headers={"Authorization": "Bearer fake"},
    )
    files = resp.json()["files"]
    assert len(files) == 3
