"""Compute STT upload must be size-gated like storage/archive (GAP-G2 parity).

`/api/v1/compute/stt` was the last upload route still doing an unbounded
`await file.read()` — a large multipart materialised the entire body in
memory before any size check ran, OOM-ing the worker. It now uses the same
`read_bounded(file, settings.max_upload_size)` helper as storage.py:106
and archive.py:131, which raises 413 mid-stream before the buffer can
grow past the limit. Mirrors test_wave7_g2_upload_size_gate.py.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def small_limit(monkeypatch):
    """Shrink max_upload_size to 4 KB so we don't have to stream MBs."""
    from api.app.config import settings

    monkeypatch.setattr(settings, "max_upload_size", 4096)
    return 4096


@pytest.fixture
def force_mock_stt(monkeypatch):
    """Force the Mock STT provider regardless of local env.

    _get_stt_provider() prefers RunPod, then SageMaker; blank those out
    so the test is deterministic on machines with real provider keys.
    (The conftest `client` fixture already sets use_mock_providers=True,
    but re-assert it here so this file doesn't depend on that detail.)
    """
    from api.app.config import settings

    monkeypatch.setattr(settings, "runpod_api_key", "")
    monkeypatch.setattr(settings, "sagemaker_endpoint_name", "")
    monkeypatch.setattr(settings, "use_mock_providers", True)


@pytest.mark.asyncio
async def test_stt_oversized_upload_413(client, small_limit, force_mock_stt):
    """A multipart upload whose file field exceeds the limit → 413."""
    oversized = b"A" * (small_limit + 1024)
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("big.opus", oversized, "audio/opus")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 413
    assert "exceeds maximum size" in resp.text


@pytest.mark.asyncio
async def test_stt_under_limit_not_gated(client, small_limit, force_mock_stt):
    """Control: a legitimate upload under the limit is not 413'd.

    Key assertion is NOT-413 (the gate must not fire); the happy path
    through the mock provider should be 200, but this test only guards
    the size gate — mirror of the frozen-gate control-test hedging.
    """
    payload = b"B" * (small_limit - 128)
    resp = await client.post(
        "/api/v1/compute/stt",
        files={"file": ("ok.opus", payload, "audio/opus")},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code != 413, resp.text
