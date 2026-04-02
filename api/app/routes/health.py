"""Health check and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from api.app.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "windy-cloud", "version": "0.1.0"}


@router.get("/api/v1/status")
async def status():
    return {
        "service": "windy-cloud",
        "version": "0.1.0",
        "pillars": {
            "storage": {"enabled": settings.r2_configured, "provider": "r2"},
            "compute": {"enabled": bool(settings.runpod_api_key), "provider": "runpod"},
            "servers": {"enabled": bool(settings.aws_access_key_id), "provider": "aws_ec2"},
        },
    }
