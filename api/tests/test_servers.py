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
async def test_create_server_with_mock(client):
    """Server creation should work with mock provider."""
    resp = await client.post(
        "/api/v1/servers/create",
        json={"plan": "starter", "region": "us-east-1", "image": "ubuntu-24-04"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["server_id"] is not None


@pytest.mark.asyncio
async def test_create_and_list_servers(client):
    """Created servers should appear in the list."""
    # Create two servers
    for plan in ("starter", "basic"):
        await client.post(
            "/api/v1/servers/create",
            json={"plan": plan, "region": "us-east-1", "image": "ubuntu-24-04"},
            headers={"Authorization": "Bearer fake"},
        )

    resp = await client.get(
        "/api/v1/servers",
        headers={"Authorization": "Bearer fake"},
    )
    body = resp.json()
    assert body["total"] == 2
    assert len(body["servers"]) == 2


@pytest.mark.asyncio
async def test_get_server_details(client):
    """Should return server details by ID."""
    # Create
    resp = await client.post(
        "/api/v1/servers/create",
        json={
            "plan": "starter",
            "region": "us-east-1",
            "image": "ubuntu-24-04",
            "hostname": "my-server",
        },
        headers={"Authorization": "Bearer fake"},
    )
    server_id = resp.json()["server_id"]

    # Get details
    resp = await client.get(
        f"/api/v1/servers/{server_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["server_id"] == server_id
    assert body["plan_id"] == "starter"
    assert body["region"] == "us-east-1"
    assert body["hostname"] == "my-server"
    assert body["status"] == "running"
    assert body["ip_address"] is not None


@pytest.mark.asyncio
async def test_server_stop_action(client):
    """Should be able to stop a running server."""
    # Create
    resp = await client.post(
        "/api/v1/servers/create",
        json={"plan": "starter", "region": "us-east-1", "image": "ubuntu-24-04"},
        headers={"Authorization": "Bearer fake"},
    )
    server_id = resp.json()["server_id"]

    # Stop
    resp = await client.post(
        f"/api/v1/servers/{server_id}/action",
        json={"action": "stop"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "stop"
    assert resp.json()["status"] == "stopped"


@pytest.mark.asyncio
async def test_server_reboot_action(client):
    """Should be able to reboot a server."""
    resp = await client.post(
        "/api/v1/servers/create",
        json={"plan": "starter", "region": "us-east-1", "image": "ubuntu-24-04"},
        headers={"Authorization": "Bearer fake"},
    )
    server_id = resp.json()["server_id"]

    resp = await client.post(
        f"/api/v1/servers/{server_id}/action",
        json={"action": "reboot"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


@pytest.mark.asyncio
async def test_delete_server(client):
    """Should be able to delete/terminate a server."""
    resp = await client.post(
        "/api/v1/servers/create",
        json={"plan": "starter", "region": "us-east-1", "image": "ubuntu-24-04"},
        headers={"Authorization": "Bearer fake"},
    )
    server_id = resp.json()["server_id"]

    # Delete
    resp = await client.delete(
        f"/api/v1/servers/{server_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # Should not appear in list (terminated)
    resp = await client.get(
        "/api/v1/servers",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.json()["total"] == 0


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


@pytest.mark.asyncio
async def test_create_server_invalid_plan(client):
    """Creating a server with unknown plan should return 400."""
    resp = await client.post(
        "/api/v1/servers/create",
        json={"plan": "nonexistent-plan", "region": "us-east-1"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
    assert "Unknown plan" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_server_lifecycle(client):
    """Full lifecycle: create → stop → start → delete."""
    # Create
    resp = await client.post(
        "/api/v1/servers/create",
        json={"plan": "basic", "region": "us-west-2", "image": "ubuntu-24-04"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    server_id = resp.json()["server_id"]

    # Stop
    resp = await client.post(
        f"/api/v1/servers/{server_id}/action",
        json={"action": "stop"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.json()["status"] == "stopped"

    # Start
    resp = await client.post(
        f"/api/v1/servers/{server_id}/action",
        json={"action": "start"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.json()["status"] == "running"

    # Delete
    resp = await client.delete(
        f"/api/v1/servers/{server_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.json()["deleted"] is True
