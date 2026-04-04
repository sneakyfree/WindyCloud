"""Health check and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from api.app.__version__ import __version__
from api.app.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "windy-cloud", "version": __version__}


@router.get("/api/v1/status")
async def status_endpoint():
    # Storage is always enabled — falls back to local disk
    storage_enabled = True
    compute_enabled = (
        bool(settings.runpod_api_key)
        or bool(settings.sagemaker_endpoint_name)
        or settings.use_mock_providers
    )
    servers_enabled = bool(settings.aws_access_key_id) or settings.use_mock_providers

    def _provider(real: str, is_real: bool) -> str:
        if is_real:
            return real
        if settings.use_mock_providers:
            return "mock"
        return "none"

    return {
        "service": "windy-cloud",
        "version": __version__,
        "pillars": {
            "storage": {
                "enabled": storage_enabled,
                "provider": "r2" if settings.r2_configured else "local_disk",
            },
            "compute": {
                "enabled": compute_enabled,
                "provider": _provider(
                    "runpod" if settings.runpod_api_key else "sagemaker",
                    bool(settings.runpod_api_key) or bool(settings.sagemaker_endpoint_name),
                ),
            },
            "servers": {
                "enabled": servers_enabled,
                "provider": _provider("aws_ec2", bool(settings.aws_access_key_id)),
            },
        },
    }
