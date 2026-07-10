"""Billing endpoint tests — usage tracking, summary, free tier."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_billing_usage_empty(client):
    """Billing usage with no activity returns zeros."""
    resp = await client.get(
        "/api/v1/billing/usage",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["storage"]["used_bytes"] == 0
    assert body["storage"]["file_count"] == 0
    assert body["compute"]["total_seconds"] == 0
    assert body["total_cost_cents"] == 0


@pytest.mark.asyncio
async def test_billing_usage_tracks_storage(client):
    """Uploading files updates billing storage counters."""
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("a.txt", b"x" * 500, "text/plain")},
        headers={"Authorization": "Bearer fake"},
    )
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("b.txt", b"y" * 300, "text/plain")},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/billing/usage",
        headers={"Authorization": "Bearer fake"},
    )
    body = resp.json()
    assert body["storage"]["used_bytes"] == 800
    assert body["storage"]["file_count"] == 2


@pytest.mark.asyncio
async def test_billing_usage_tracks_compute(client):
    """STT transcription updates billing compute counters."""
    await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"\x00" * 32000, "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/billing/usage",
        headers={"Authorization": "Bearer fake"},
    )
    body = resp.json()
    assert body["compute"]["total_jobs"] == 1
    assert body["compute"]["total_seconds"] > 0


@pytest.mark.asyncio
async def test_billing_summary_endpoint(client):
    """GET /api/v1/billing/summary returns human-readable usage."""
    resp = await client.get(
        "/api/v1/billing/summary",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "storage_used" in body
    assert "storage_quota" in body
    assert "compute_minutes_used" in body
    assert "compute_free_remaining" in body


@pytest.mark.asyncio
async def test_billing_history_empty(client):
    """Billing history with no data returns empty list."""
    resp = await client.get(
        "/api/v1/billing/history",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


@pytest.mark.asyncio
async def test_billing_estimate(client):
    """Billing estimate returns cost projection."""
    resp = await client.get(
        "/api/v1/billing/estimate",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "storage_cost_cents" in body
    assert "compute_cost_cents" in body
    assert "total_estimated_cents" in body


@pytest.mark.asyncio
async def test_billing_sync_returns_usage(client):
    """POST /api/v1/billing/sync returns usage for a specific identity."""
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("data.bin", b"z" * 1000, "application/octet-stream")},
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


@pytest.mark.asyncio
async def test_billing_sync_cross_identity_forbidden(client):
    """[B2] A non-admin user may not sync another identity's usage (IDOR)."""
    resp = await client.post(
        "/api/v1/billing/sync",
        json={"windy_identity_id": "someone-else-999"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_free_tier_compute(client):
    """First 10 minutes of STT should be free."""
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("short.wav", b"\x00" * 16000, "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Short file within free tier should cost $0
    assert body["cost_cents"] == 0
