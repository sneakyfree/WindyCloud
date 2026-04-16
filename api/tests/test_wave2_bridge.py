"""Tests for the passport ↔ identity bridge (Wave 2 contract #3)."""

from __future__ import annotations

import pytest


TOKEN = "bridge-test-token"


@pytest.fixture
def service_token(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", TOKEN)
    return TOKEN


@pytest.mark.asyncio
async def test_link_and_lookup(client, service_token):
    resp = await client.post(
        "/api/v1/identity/link-passport",
        json={"windy_identity_id": "id-a", "passport_number": "ET-A"},
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        "/api/v1/identity/by-passport/ET-A",
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200
    assert resp.json()["windy_identity_id"] == "id-a"


@pytest.mark.asyncio
async def test_link_is_idempotent(client, service_token):
    for _ in range(3):
        resp = await client.post(
            "/api/v1/identity/link-passport",
            json={"windy_identity_id": "id-b", "passport_number": "ET-B"},
            headers={"X-Service-Token": service_token},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_lookup_404_for_unknown(client, service_token):
    resp = await client.get(
        "/api/v1/identity/by-passport/ET-MISSING",
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_link_requires_service_token(client):
    resp = await client.post(
        "/api/v1/identity/link-passport",
        json={"windy_identity_id": "id-c", "passport_number": "ET-C"},
    )
    assert resp.status_code == 422  # missing header


@pytest.mark.asyncio
async def test_lookup_rejects_bad_service_token(client, service_token):
    resp = await client.get(
        "/api/v1/identity/by-passport/ET-A",
        headers={"X-Service-Token": "wrong"},
    )
    assert resp.status_code == 401
