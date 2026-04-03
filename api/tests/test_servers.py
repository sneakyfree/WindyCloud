"""VPS server endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_plans(client):
    """Plans endpoint should list available VPS plans."""
    resp = await client.get(
        "/api/v1/servers/plans",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    plans = resp.json()["plans"]
    assert len(plans) == 5
    assert plans[0]["plan_id"] == "starter"
    assert plans[0]["price_cents_per_month"] == 500


@pytest.mark.asyncio
async def test_list_servers_empty(client):
    """Should return empty list when no servers exist."""
    resp = await client.get(
        "/api/v1/servers",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["servers"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_create_server_503_without_aws(client):
    """Server creation should return 503 when AWS isn't configured."""
    resp = await client.post(
        "/api/v1/servers/create",
        json={"plan": "starter", "region": "us-east-1", "image": "ubuntu-24-04"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_nonexistent_server(client):
    """Getting a non-existent server should return 404."""
    resp = await client.get(
        "/api/v1/servers/nonexistent-id",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_server(client):
    """Deleting a non-existent server should return 404."""
    resp = await client.delete(
        "/api/v1/servers/nonexistent-id",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_action_nonexistent_server(client):
    """Action on non-existent server should return 404."""
    resp = await client.post(
        "/api/v1/servers/nonexistent-id/action",
        json={"action": "start"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_action_invalid_action(client):
    """Invalid action should return 400."""
    resp = await client.post(
        "/api/v1/servers/some-id/action",
        json={"action": "explode"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
    assert "start, stop, or reboot" in resp.json()["detail"]
