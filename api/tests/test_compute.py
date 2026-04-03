"""Compute (STT) endpoint tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_stt_mock_transcription(client):
    """STT should return a mock transcription when mock providers are enabled."""
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"fake-audio-data" * 100, "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["text"] is not None
    assert len(body["segments"]) == 2
    assert body["duration_seconds"] > 0
    assert body["language"] == "en"


@pytest.mark.asyncio
async def test_stt_with_language_param(client):
    """STT should accept a language parameter."""
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"fake-audio" * 50, "audio/wav")},
        data={"language": "es", "model": "medium"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["language"] == "es"


@pytest.mark.asyncio
async def test_stt_empty_file_rejected(client):
    """STT should reject empty audio files."""
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"", "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 400
    assert "Empty" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_stt_job_retrieval(client):
    """After submitting STT, the job should be retrievable by ID."""
    # Submit transcription
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"fake-audio-data" * 100, "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # Retrieve job
    resp = await client.get(
        f"/api/v1/compute/stt/{job_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["status"] == "completed"
    assert body["result"] is not None
    assert body["result"]["text"] is not None


@pytest.mark.asyncio
async def test_stt_updates_usage(client):
    """STT transcription should update compute usage."""
    # Check initial usage
    resp = await client.get(
        "/api/v1/compute/usage",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.json()["total_jobs"] == 0

    # Submit transcription
    await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"fake-audio-data" * 100, "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )

    # Check updated usage
    resp = await client.get(
        "/api/v1/compute/usage",
        headers={"Authorization": "Bearer fake"},
    )
    body = resp.json()
    assert body["total_jobs"] == 1
    assert body["total_seconds"] > 0


@pytest.mark.asyncio
async def test_stt_free_tier_no_cost(client):
    """Short transcriptions within free tier should have zero cost."""
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("audio.wav", b"tiny", "audio/wav")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    # Free tier covers 10 minutes, tiny file is well within
    assert resp.json()["cost_cents"] == 0


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
