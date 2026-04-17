"""Bounded upload reader — reject oversized bodies mid-stream.

Wave 7 GAP G2 fix. The original pattern:

    data = await file.read()
    if len(data) > max_upload_size: raise 413

materialises the entire body into a Python `bytes` object *before* the
size check runs. On 1 GB Fargate tasks with a 1 GB max size, one legit
max-sized upload OOMs the worker.

`read_bounded` reads in fixed-size chunks and raises 413 the moment
the running total exceeds `max_bytes`, so the in-memory buffer never
grows past the limit.

The chunked enforcement is the *only* check we need: an ALB /
nginx-level `client_max_body_size` at the edge handles oversized
bodies before they reach us, and this helper is the defense-in-depth
inside the pod. A pre-handler Content-Length fast-path was tried and
removed — FastAPI's multipart parser resolves before in-handler code,
so the pre-check fired too late to avoid the OOM window it was
supposed to protect, and caused false-positives on legitimate uploads
whose multipart envelope was marginally larger than the file limit.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

# 1 MB read chunks — small enough to keep the short-circuit tight,
# large enough to not thrash the event loop.
CHUNK_SIZE = 1 << 20


def _oversize(limit: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"File exceeds maximum size of {limit} bytes",
    )


async def read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read `file` into memory, but raise 413 as soon as we exceed `max_bytes`.

    Matches the old `await file.read()` return type (bytes) so call
    sites can swap in without further changes.
    """
    buf = bytearray()
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        if len(buf) + len(chunk) > max_bytes:
            # Drop the buffer eagerly so the 413 response doesn't also
            # carry the oversized bytes in memory.
            buf = bytearray()
            raise _oversize(max_bytes)
        buf.extend(chunk)
    return bytes(buf)
