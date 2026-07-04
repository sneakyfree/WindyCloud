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


@pytest.mark.asyncio
async def test_archive_clone(client):
    """Clone archive endpoint stores voice/audio/text for AI avatars."""
    resp = await client.post(
        "/api/v1/archive/clone",
        files={"file": ("voice.wav", b"audio-bytes", "audio/wav")},
        data={"metadata": json.dumps({"file_type": "voice"})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["product"] == "windy_clone"
    assert body["type"] == "clone_data"


@pytest.mark.asyncio
async def test_archive_list(client):
    """The list endpoint enumerates a caller's files for a product,
    newest first — the piece backup/restore clients were missing."""
    # Upload two agent backups.
    for name in ("backup-1.enc", "backup-2.enc"):
        r = await client.post(
            "/api/v1/archive/agent",
            files={"file": (name, b"data-" + name.encode(), "application/octet-stream")},
            data={"metadata": json.dumps({}), "filename": name},
            headers={"Authorization": "Bearer fake"},
        )
        assert r.status_code == 200

    resp = await client.get(
        "/api/v1/archive/list/windy_fly",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["product"] == "windy_fly"
    assert body["count"] >= 2
    names = [f["filename"] for f in body["files"]]
    assert "backup-1.enc" in names and "backup-2.enc" in names
    # each entry carries the fields a restore client needs
    assert all({"file_id", "filename", "size_bytes", "created_at"} <= set(f) for f in body["files"])


@pytest.mark.asyncio
async def test_archive_list_then_retrieve_round_trip(client):
    """List → retrieve is the canonical backup/restore path."""
    await client.post(
        "/api/v1/archive/agent",
        files={"file": ("rt.enc", b"round-trip-payload", "application/octet-stream")},
        data={"metadata": json.dumps({}), "filename": "rt.enc"},
        headers={"Authorization": "Bearer fake"},
    )
    listed = (await client.get(
        "/api/v1/archive/list/windy_fly",
        headers={"Authorization": "Bearer fake"},
    )).json()
    fname = listed["files"][0]["filename"]
    got = await client.get(
        f"/api/v1/archive/retrieve/windy_fly/{fname}",
        headers={"Authorization": "Bearer fake"},
    )
    assert got.status_code == 200
    assert got.content == b"round-trip-payload"
