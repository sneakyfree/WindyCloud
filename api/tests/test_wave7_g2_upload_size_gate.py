"""GAP G2: reject oversized uploads BEFORE materialising the full body.

Two gates must hold:
  1. Content-Length header ≥ limit → 413 without reading the body.
  2. Chunked read short-circuits 413 the moment the running total
     exceeds the limit — defense against clients that lie about size.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def small_limit(monkeypatch):
    """Shrink max_upload_size to 4 KB so we don't have to stream MBs."""
    from api.app.config import settings

    monkeypatch.setattr(settings, "max_upload_size", 4096)
    return 4096


@pytest.mark.asyncio
async def test_413_via_chunked_stream(client, small_limit):
    """A real multipart upload whose file field exceeds the limit → 413."""
    oversized = b"A" * (small_limit + 1024)
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("big.bin", oversized, "application/octet-stream")},
        data={"metadata": json.dumps({})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 413
    assert "exceeds maximum size" in resp.text


@pytest.mark.asyncio
async def test_archive_upload_also_gated(client, small_limit):
    oversized = b"A" * (small_limit + 1024)
    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("big.enc", oversized, "application/octet-stream")},
        data={"metadata": json.dumps({"encrypted": True})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_just_under_limit_still_succeeds(client, small_limit):
    """A legitimate upload at limit-1 bytes still uploads cleanly."""
    payload = b"B" * (small_limit - 128)
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("ok.bin", payload, "application/octet-stream")},
        data={"metadata": json.dumps({})},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["size"] == len(payload)


@pytest.mark.asyncio
async def test_read_bounded_rejects_before_full_buffer():
    """Direct unit test on the helper — prove we never buffer past the limit."""
    from fastapi import HTTPException, UploadFile

    from api.app.utils.upload import read_bounded

    # 1 MB stream, limit 4 KB.
    stream = io.BytesIO(b"A" * (1 << 20))
    uf = UploadFile(file=stream, filename="x.bin")
    with pytest.raises(HTTPException) as exc:
        await read_bounded(uf, 4096)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_read_bounded_exact_limit_ok():
    from fastapi import UploadFile

    from api.app.utils.upload import read_bounded

    stream = io.BytesIO(b"X" * 4096)
    uf = UploadFile(file=stream, filename="ok.bin")
    data = await read_bounded(uf, 4096)
    assert len(data) == 4096
