"""GAP G13: archive_migrate uses service-token auth, not user JWT.

Wave 2 swapped the five /archive/{product} upload endpoints from
`get_current_user` to `get_user_or_service`. `archive_migrate` got
missed — product backends calling it had to forge a user JWT. This
test pins the new behaviour: service-token required, JWT not enough.
"""

from __future__ import annotations

import pytest


TOKEN = "g13-svc-token"


@pytest.fixture
def service_token(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", TOKEN)
    return TOKEN


@pytest.mark.asyncio
async def test_migrate_rejects_without_service_token(client):
    resp = await client.post(
        "/api/v1/archive/migrate",
        json={
            "product": "windy_chat",
            "windy_identity_id": "user-1",
            "files": [
                {
                    "filename": "a.enc",
                    "size": 100,
                    "content_type": "application/octet-stream",
                    "encrypted": True,
                }
            ],
        },
        headers={"Authorization": "Bearer fake"},  # JWT is no longer enough
    )
    # Missing X-Service-Token → 422 (FastAPI Header required) or 401.
    assert resp.status_code in (401, 422), (
        f"JWT-only caller should be rejected; got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_migrate_rejects_with_wrong_service_token(client, service_token):
    resp = await client.post(
        "/api/v1/archive/migrate",
        json={
            "product": "windy_chat",
            "windy_identity_id": "user-1",
            "files": [],
        },
        headers={"X-Service-Token": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_migrate_accepts_valid_service_token(client, service_token):
    resp = await client.post(
        "/api/v1/archive/migrate",
        json={
            "product": "windy_chat",
            "windy_identity_id": "product-target-user",
            "files": [
                {
                    "filename": "batch-a.enc",
                    "size": 1024,
                    "content_type": "application/octet-stream",
                    "encrypted": True,
                    "retention_days": 90,
                },
                {
                    "filename": "batch-b.enc",
                    "size": 2048,
                    "content_type": "application/octet-stream",
                    "encrypted": True,
                    "retention_count": 7,
                },
            ],
        },
        headers={"X-Service-Token": service_token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["product"] == "windy_chat"
    assert body["identity_id"] == "product-target-user"
    assert body["migrated"] == 2


@pytest.mark.asyncio
async def test_migrate_is_idempotent_for_existing_files(client, service_token):
    """Calling migrate twice for the same (identity, product, filename)
    must re-register retention, not 500."""
    payload = {
        "product": "windy_mail",
        "windy_identity_id": "idem-user",
        "files": [
            {
                "filename": "q2-dump.sql.gz",
                "size": 50_000_000,
                "content_type": "application/gzip",
                "retention_days": 90,
            }
        ],
    }
    r1 = await client.post(
        "/api/v1/archive/migrate",
        json=payload,
        headers={"X-Service-Token": service_token},
    )
    assert r1.status_code == 200
    assert r1.json()["results"][0]["status"] == "migrated"

    # Second call with updated retention
    payload["files"][0]["retention_days"] = 180
    r2 = await client.post(
        "/api/v1/archive/migrate",
        json=payload,
        headers={"X-Service-Token": service_token},
    )
    assert r2.status_code == 200
    assert r2.json()["results"][0]["status"] == "already_exists"
