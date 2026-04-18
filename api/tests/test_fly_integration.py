"""Windy Fly integration tests.

Verifies the Cloud API matches what the windy-agent client expects:
- POST /api/v1/storage/upload (multipart + Bearer auth)
- GET /api/v1/storage/health (public)
- GET /api/v1/files (agent-compat alias for /api/v1/storage/files)
- GET /api/v1/billing/summary (agent-compat)
"""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_upload_multipart_with_bearer(client):
    """Agent uploads via POST /api/v1/storage/upload with multipart form data."""
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("agent_memory.db", b"agent-db-content", "application/x-sqlite3")},
        data={
            "product": "windy_fly",
            "file_type": "agent_backup",
            "metadata": json.dumps({"agent_name": "Aria", "passport_id": "ET-1234"}),
        },
        headers={"Authorization": "Bearer fake-agent-jwt"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "file_id" in body
    assert "key" in body
    assert body["size"] > 0
    assert body["content_type"] == "application/x-sqlite3"
    assert body["message"] == "File uploaded successfully"


@pytest.mark.asyncio
async def test_storage_health_response_format(client):
    """GET /api/v1/storage/health returns {status, provider}."""
    resp = await client.get("/api/v1/storage/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert "provider" in body


@pytest.mark.asyncio
async def test_root_health_response_format(client):
    """GET /health returns {status, service} — G31 moved version etc. to /health/full."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "windy-cloud"
    # version moved to /health/full post-G31 (deployment metadata leak)
    full = await client.get("/health/full")
    assert "version" in full.json()


@pytest.mark.asyncio
async def test_agent_compat_files_alias(client):
    """Agent calls GET /api/v1/files — compat alias for /api/v1/storage/files."""
    # Upload a file first
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
        data={"product": "windy_fly"},
        headers={"Authorization": "Bearer fake"},
    )

    # List via the agent-compat path
    resp = await client.get(
        "/api/v1/files",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "files" in body
    assert "total" in body
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_billing_summary_endpoint(client):
    """Agent calls GET /api/v1/billing/summary for storage command."""
    resp = await client.get(
        "/api/v1/billing/summary",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "identity_id" in body
    assert "storage_used" in body
    assert "storage_quota" in body
    assert "storage_percent" in body
    assert "compute_minutes_used" in body
    assert "compute_free_remaining" in body
    assert "total_cost_cents" in body


@pytest.mark.asyncio
async def test_billing_sync_endpoint(client):
    """Windy Pro calls POST /api/v1/billing/sync to pull usage for Stripe."""
    # Upload a file to create usage
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("data.bin", b"x" * 1000, "application/octet-stream")},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.post(
        "/api/v1/billing/sync",
        json={"windy_identity_id": "test-user-001"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["identity_id"] == "test-user-001"
    assert body["storage_bytes"] == 1000
    assert body["storage_file_count"] == 1
    assert "compute_minutes" in body
    assert "server_count" in body
    assert "total_cost_cents" in body


@pytest.mark.asyncio
async def test_upload_response_matches_agent_parser(client):
    """Verify upload response has all fields the agent client expects to parse."""
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("recording.opus", b"audio-bytes", "audio/opus")},
        data={"product": "windy_pro", "file_type": "recording"},
        headers={"Authorization": "Bearer fake"},
    )
    body = resp.json()

    # These are the fields the agent will access
    assert isinstance(body["file_id"], str)
    assert isinstance(body["key"], str)
    assert isinstance(body["size"], int)
    assert isinstance(body["content_type"], str)
    # Key should follow the namespaced format
    assert body["key"].startswith("test-user-001/windy_pro/recording/")
