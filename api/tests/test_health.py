"""Health endpoint tests — comprehensive provider checks."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_comprehensive(client):
    """Health endpoint returns all provider statuses."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert body["service"] == "windy-cloud"
    assert "version" in body
    assert body["database"] in ("ok", "error")
    assert "storage_provider" in body
    assert isinstance(body["storage_healthy"], bool)
    assert "compute_provider" in body
    assert isinstance(body["compute_healthy"], bool)
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_health_storage_provider_local(client):
    """In test mode, storage provider is local_disk."""
    resp = await client.get("/health")
    body = resp.json()
    assert body["storage_provider"] == "local_disk"
    assert body["storage_healthy"] is True


@pytest.mark.asyncio
async def test_health_compute_mock(client):
    """In test mode with mock providers, compute is available."""
    resp = await client.get("/health")
    body = resp.json()
    assert body["compute_provider"] == "mock"
    assert body["compute_healthy"] is True


@pytest.mark.asyncio
async def test_status_endpoint(client):
    """Status endpoint returns pillar details."""
    resp = await client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pillars"]["storage"]["enabled"] is True
    assert body["pillars"]["compute"]["enabled"] is True
    assert body["pillars"]["servers"]["enabled"] is True
