"""Deploy-Fly endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_deploy_fly_provisions_server(client):
    """POST /api/v1/servers/deploy-fly provisions a Windy Fly agent server."""
    resp = await client.post(
        "/api/v1/servers/deploy-fly",
        json={"plan": "starter", "agent_name": "aria"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan_id"] == "starter"
    assert body["agent_name"] == "aria"
    assert body["hostname"] == "aria.windyfly.ai"
    assert body["status"] in ("provisioning", "running")
    assert "server_id" in body


@pytest.mark.asyncio
async def test_deploy_fly_default_name(client):
    """Deploy without agent_name generates one from identity."""
    resp = await client.post(
        "/api/v1/servers/deploy-fly",
        json={"plan": "starter"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_name"].startswith("fly-")


@pytest.mark.asyncio
async def test_deploy_fly_invalid_plan(client):
    """Invalid plan returns 400."""
    resp = await client.post(
        "/api/v1/servers/deploy-fly",
        json={"plan": "nonexistent"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
