"""Compute (STT) endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_stt_returns_503_when_not_configured(client):
    """STT should return 503 when RunPod isn't configured."""
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"fake-audio", "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_compute_usage_empty(client):
    """Compute usage should return zeros when no jobs have run."""
    resp = await client.get(
        "/api/v1/compute/usage",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_seconds"] == 0
    assert body["total_jobs"] == 0
    assert body["total_cost_cents"] == 0
    assert body["free_minutes_remaining"] == 10.0


@pytest.mark.asyncio
async def test_list_models(client):
    """Models endpoint should list available STT models."""
    resp = await client.get(
        "/api/v1/compute/models",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["models"]) == 3
    assert body["models"][0]["model_id"] == "large-v3"
    assert body["free_minutes_per_month"] == 10


@pytest.mark.asyncio
async def test_get_nonexistent_job(client):
    """Getting a non-existent job should return 404."""
    resp = await client.get(
        "/api/v1/compute/stt/nonexistent-id",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_billing_usage(client):
    """Billing usage should return combined storage + compute summary."""
    resp = await client.get(
        "/api/v1/billing/usage",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "storage" in body
    assert "compute" in body
    assert body["storage"]["used_bytes"] == 0
    assert body["compute"]["total_jobs"] == 0


@pytest.mark.asyncio
async def test_billing_history(client):
    """Billing history should return an empty list initially."""
    resp = await client.get(
        "/api/v1/billing/history",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


@pytest.mark.asyncio
async def test_billing_estimate(client):
    """Billing estimate should return cost estimates."""
    resp = await client.get(
        "/api/v1/billing/estimate",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["storage_cost_cents"] == 0
    assert body["compute_cost_cents"] == 0
    assert body["total_estimated_cents"] == 0
