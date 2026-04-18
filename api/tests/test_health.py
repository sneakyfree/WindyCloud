"""Health endpoint tests — public surface is minimal, /health/full has detail.

Wave 7 G31 moved the deployment-metadata fields (storage_provider,
compute_provider, storage_healthy, compute_healthy, version, uptime_seconds)
off the public `/health` onto `/health/full`. Public `/health` now
returns only `{status, service}`.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_public_health_is_minimal(client):
    """Public /health is intentionally minimal — status + service only."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert body["service"] == "windy-cloud"
    assert set(body.keys()) == {"status", "service"}


@pytest.mark.asyncio
async def test_health_full_has_all_provider_details(client):
    """The detailed probe lives at /health/full for internal ALB checks."""
    resp = await client.get("/health/full")
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
async def test_health_full_storage_provider_local(client):
    """In test mode, storage provider is local_disk — on /health/full."""
    resp = await client.get("/health/full")
    body = resp.json()
    assert body["storage_provider"] == "local_disk"
    assert body["storage_healthy"] is True


@pytest.mark.asyncio
async def test_health_full_compute_mock(client):
    """In test mode with mock providers, compute is available — on /health/full."""
    resp = await client.get("/health/full")
    body = resp.json()
    assert body["compute_provider"] == "mock"
    assert body["compute_healthy"] is True


@pytest.mark.asyncio
async def test_status_endpoint_pillars_no_provider_leak(client):
    """Status returns pillar on/off, not backend names (G31)."""
    resp = await client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    for pillar_name, pillar in body["pillars"].items():
        assert pillar["enabled"] is True
        # Backends intentionally removed — the public status only
        # confirms a pillar is on.
        assert "provider" not in pillar, f"{pillar_name} pillar still leaks provider: {pillar}"
