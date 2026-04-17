"""Health check and status endpoints.

Wave 7 G31 — `/health` and `/api/v1/status` are reachable by anyone on
the internet. Pre-G31 they leaked deployment metadata:

  - which storage backend is wired (R2 vs local-disk-fallback)
  - which compute backend (runpod / sagemaker / none)
  - whether AWS keys are present
  - the Python version string via uvicorn server header (separate)

All of that tells an attacker exactly what to target. This module now
returns minimal info on the public paths and puts the detailed
provider breakdown behind `/health/full`, which we expose only on a
loopback ALB target-group health check path in prod.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from api.app.__version__ import __version__
from api.app.config import settings

router = APIRouter()

_start_time = time.monotonic()


async def _check_db() -> bool:
    try:
        from sqlalchemy import text

        from api.app.db.engine import async_session

        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_storage() -> bool:
    try:
        if settings.r2_configured:
            from api.app.providers.r2 import R2StorageProvider

            return await R2StorageProvider().health()
        from api.app.providers.local_disk import LocalDiskProvider

        return await LocalDiskProvider().health()
    except Exception:
        return False


async def _check_compute() -> bool:
    try:
        if settings.runpod_api_key:
            from api.app.providers.runpod import RunPodSTTProvider

            return await RunPodSTTProvider().health()
        if settings.sagemaker_endpoint_name and settings.aws_access_key_id:
            from api.app.providers.sagemaker import SageMakerSTTProvider

            return await SageMakerSTTProvider().health()
        if settings.use_mock_providers:
            return True
        return False
    except Exception:
        return False


def _storage_provider() -> str:
    if settings.r2_configured:
        return "r2"
    return "local_disk"


def _compute_provider() -> str:
    if settings.runpod_api_key:
        return "runpod"
    if settings.sagemaker_endpoint_name:
        return "sagemaker"
    if settings.use_mock_providers:
        return "mock"
    return "none"


async def _gather_health_checks():
    try:
        db_ok, storage_ok, compute_ok = await asyncio.wait_for(
            asyncio.gather(
                _check_db(),
                _check_storage(),
                _check_compute(),
                return_exceptions=True,
            ),
            timeout=5.0,
        )
        db_ok = db_ok if isinstance(db_ok, bool) else False
        storage_ok = storage_ok if isinstance(storage_ok, bool) else False
        compute_ok = compute_ok if isinstance(compute_ok, bool) else False
    except asyncio.TimeoutError:
        db_ok = storage_ok = compute_ok = False
    return db_ok, storage_ok, compute_ok


@router.get("/health")
async def health():
    """Public health probe — safe to expose on the public ALB.

    Returns only the overall status and uptime. Does NOT disclose which
    storage / compute backends are wired or whether they're healthy —
    that's deployment metadata an attacker could use to target this pod.
    """
    db_ok, storage_ok, _compute_ok = await _gather_health_checks()
    overall = "ok" if db_ok and storage_ok else "degraded"
    return {
        "status": overall,
        "service": "windy-cloud",
    }


@router.get("/health/full", include_in_schema=False)
async def health_full():
    """Detailed health for internal ALB target-group checks.

    Expose only on an internal listener — the provider names and
    per-backend health flags are the pieces G31 removed from the
    public probe.
    """
    uptime = round(time.monotonic() - _start_time)
    db_ok, storage_ok, compute_ok = await _gather_health_checks()
    overall = "ok" if db_ok and storage_ok else "degraded"

    return {
        "status": overall,
        "service": "windy-cloud",
        "version": __version__,
        "database": "ok" if db_ok else "error",
        "storage_provider": _storage_provider(),
        "storage_healthy": storage_ok,
        "compute_provider": _compute_provider(),
        "compute_healthy": compute_ok,
        "uptime_seconds": uptime,
    }


@router.get("/api/v1/status")
async def status_endpoint():
    """Minimal public status — only pillar-on/off booleans, no backends.

    Web portal uses this to know which pillars to render. The actual
    backend behind each pillar is not a fact the public needs to know.
    """
    storage_enabled = True
    compute_enabled = (
        bool(settings.runpod_api_key)
        or bool(settings.sagemaker_endpoint_name)
        or settings.use_mock_providers
    )
    servers_enabled = bool(settings.aws_access_key_id) or settings.use_mock_providers

    return {
        "service": "windy-cloud",
        "pillars": {
            "storage": {"enabled": storage_enabled},
            "compute": {"enabled": compute_enabled},
            "servers": {"enabled": servers_enabled},
        },
    }
