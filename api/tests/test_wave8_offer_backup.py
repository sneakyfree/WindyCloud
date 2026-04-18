"""Wave 8 — post-hatch auto-backup offer endpoint tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_offer_backup_first_call_queues_and_notifies(client):
    """Happy path: first ping persists the offer and fires the Chat push."""
    with patch(
        "api.app.routes.sync.send_first_backup_notification",
        new=AsyncMock(return_value=True),
    ) as push:
        resp = await client.post(
            "/api/v1/sync/offer-backup",
            json={"recording_count": 7, "bytes_estimated": 1_000_000},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["recording_count"] == 7
    assert body["notified"] is True
    push.assert_awaited_once()


@pytest.mark.asyncio
async def test_offer_backup_is_idempotent_per_identity(client):
    """Second call for the same identity must not re-notify."""
    with patch(
        "api.app.routes.sync.send_first_backup_notification",
        new=AsyncMock(return_value=True),
    ) as push:
        first = await client.post(
            "/api/v1/sync/offer-backup",
            json={"recording_count": 3},
            headers={"Authorization": "Bearer fake"},
        )
        assert first.status_code == 200
        assert first.json()["status"] == "queued"

        second = await client.post(
            "/api/v1/sync/offer-backup",
            json={"recording_count": 99},  # count change must be ignored
            headers={"Authorization": "Bearer fake"},
        )

    assert second.status_code == 200
    second_body = second.json()
    assert second_body["status"] == "already_offered"
    assert second_body["recording_count"] == 3
    # Exactly one outbound notification despite two pings.
    assert push.await_count == 1


@pytest.mark.asyncio
async def test_offer_backup_zero_recordings_rejected(client):
    resp = await client.post(
        "/api/v1/sync/offer-backup",
        json={"recording_count": 0},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_offer_backup_negative_recordings_rejected(client):
    resp = await client.post(
        "/api/v1/sync/offer-backup",
        json={"recording_count": -1},
        headers={"Authorization": "Bearer fake"},
    )
    # Pydantic validation triggers a 422 for a schema violation.
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_offer_backup_persists_even_when_push_fails(client):
    """Notification failure must not block persisting the offer row."""
    with patch(
        "api.app.routes.sync.send_first_backup_notification",
        new=AsyncMock(return_value=False),
    ):
        resp = await client.post(
            "/api/v1/sync/offer-backup",
            json={"recording_count": 2},
            headers={"Authorization": "Bearer fake"},
        )
    assert resp.status_code == 200
    assert resp.json()["notified"] is False

    # Second call must still be recognised as an existing offer.
    with patch(
        "api.app.routes.sync.send_first_backup_notification",
        new=AsyncMock(return_value=True),
    ) as push:
        repeat = await client.post(
            "/api/v1/sync/offer-backup",
            json={"recording_count": 2},
            headers={"Authorization": "Bearer fake"},
        )
    assert repeat.status_code == 200
    assert repeat.json()["status"] == "already_offered"
    push.assert_not_called()
