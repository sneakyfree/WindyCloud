"""Wave 8 — windycloud:// deep-link resolver tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_resolve_dashboard(client):
    resp = await client.get("/api/v1/deeplink/resolve", params={"target": "dashboard"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["target"] == "dashboard"
    assert body["scheme"] == "windycloud"
    assert body["web_path"] == "/"


@pytest.mark.asyncio
async def test_resolve_backup_triggers_action_path(client):
    resp = await client.get("/api/v1/deeplink/resolve", params={"target": "backup"})
    assert resp.status_code == 200
    assert resp.json()["web_path"] == "/?action=start-backup"


@pytest.mark.asyncio
async def test_resolve_usage(client):
    resp = await client.get("/api/v1/deeplink/resolve", params={"target": "usage"})
    assert resp.status_code == 200
    assert resp.json()["web_path"] == "/billing"


@pytest.mark.asyncio
async def test_resolve_plan(client):
    resp = await client.get("/api/v1/deeplink/resolve", params={"target": "plan"})
    assert resp.status_code == 200
    assert resp.json()["web_path"] == "/billing?view=upgrade"


@pytest.mark.asyncio
async def test_resolve_unknown_target_is_rejected(client):
    resp = await client.get(
        "/api/v1/deeplink/resolve", params={"target": "evil-open-redirect"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_allowlisted_params_are_appended(client):
    resp = await client.get(
        "/api/v1/deeplink/resolve",
        params={"target": "dashboard", "source": "hatch-ribbon"},
    )
    assert resp.status_code == 200
    assert resp.json()["web_path"] == "/?source=hatch-ribbon"


@pytest.mark.asyncio
async def test_unsafe_param_value_is_dropped(client):
    # Attempt to smuggle an angle-bracket through the resolver. The
    # resolver drops unsafe values rather than URL-escaping them —
    # matching the front-end guard so the two sides stay aligned.
    resp = await client.get(
        "/api/v1/deeplink/resolve",
        params={"target": "dashboard", "source": "<script>alert(1)</script>"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "script" not in body["web_path"]
    assert body["params"] == {}


@pytest.mark.asyncio
async def test_manifest_lists_all_targets(client):
    resp = await client.get("/api/v1/deeplink/manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scheme"] == "windycloud"
    targets = {t["target"] for t in body["targets"]}
    assert targets == {"dashboard", "backup", "usage", "plan"}
