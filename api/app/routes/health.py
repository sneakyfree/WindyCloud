"""Health check and status endpoints."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from api.app.__version__ import __version__
from api.app.config import settings

router = APIRouter()

_start_time = time.monotonic()


async def _check_db() -> bool:
    """Check database connectivity."""
    try:
        from sqlalchemy import text

        from api.app.db.engine import async_session

        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_storage() -> bool:
    """Check storage provider health."""
    try:
        if settings.r2_configured:
            from api.app.providers.r2 import R2StorageProvider

            return await R2StorageProvider().health()
        from api.app.providers.local_disk import LocalDiskProvider

        return await LocalDiskProvider().health()
    except Exception:
        return False


async def _check_compute() -> bool:
    """Check compute provider health."""
    try:
        if settings.runpod_api_key:
            from api.app.providers.runpod import RunPodSTTProvider

            return await RunPodSTTProvider().health()
        if settings.sagemaker_endpoint_name and settings.aws_access_key_id:
            from api.app.providers.sagemaker import SageMakerSTTProvider

            return await SageMakerSTTProvider().health()
        if settings.use_mock_providers:
            return True
        return False  # No compute configured
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


@router.get("/health")
async def health():
    """Comprehensive health check with provider status and uptime."""
    uptime = round(time.monotonic() - _start_time)

    # Run health checks concurrently with 5s timeout
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
        # Convert exceptions to False
        db_ok = db_ok if isinstance(db_ok, bool) else False
        storage_ok = storage_ok if isinstance(storage_ok, bool) else False
        compute_ok = compute_ok if isinstance(compute_ok, bool) else False
    except asyncio.TimeoutError:
        db_ok = storage_ok = compute_ok = False

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
    """Detailed pillar status for the web portal."""
    storage_enabled = True
    compute_enabled = (
        bool(settings.runpod_api_key)
        or bool(settings.sagemaker_endpoint_name)
        or settings.use_mock_providers
    )
    servers_enabled = bool(settings.aws_access_key_id) or settings.use_mock_providers

    return {
        "service": "windy-cloud",
        "version": __version__,
        "pillars": {
            "storage": {
                "enabled": storage_enabled,
                "provider": _storage_provider(),
            },
            "compute": {
                "enabled": compute_enabled,
                "provider": _compute_provider(),
            },
            "servers": {
                "enabled": servers_enabled,
                "provider": "aws_ec2"
                if settings.aws_access_key_id
                else ("mock" if settings.use_mock_providers else "none"),
            },
        },
    }
