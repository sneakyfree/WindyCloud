"""Compute endpoints — Cloud STT (speech-to-text)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.auth.dependencies import AuthenticatedUser, get_current_user
from api.app.auth.webhook import require_not_blocked_for_write
from api.app.config import settings
from api.app.db.engine import get_db
from api.app.db.models import ComputeJob, ComputeUsageRecord
from api.app.models.compute import (
    ComputeUsageResponse,
    ModelInfo,
    ModelsResponse,
    STTJobStatus,
    TranscriptionResult,
    TranscriptionSegment,
)
from api.app.utils.upload import read_bounded

router = APIRouter()


def _get_stt_provider():
    """Return the best available STT provider: RunPod → SageMaker → Mock → None."""
    if settings.runpod_api_key:
        from api.app.providers.runpod import RunPodSTTProvider

        return RunPodSTTProvider()
    if settings.sagemaker_endpoint_name and settings.aws_access_key_id:
        from api.app.providers.sagemaker import SageMakerSTTProvider

        return SageMakerSTTProvider()
    if settings.use_mock_providers:
        from api.app.providers.stt_base import MockSTTProvider

        return MockSTTProvider()
    return None


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _get_free_seconds_remaining(db: AsyncSession, identity_id: str) -> float:
    """How many free seconds remain this month."""
    month = _current_month()
    result = await db.execute(
        select(ComputeUsageRecord).where(
            ComputeUsageRecord.identity_id == identity_id,
            ComputeUsageRecord.month == month,
        )
    )
    record = result.scalar_one_or_none()
    used = record.total_seconds if record else 0.0
    free_seconds = settings.stt_free_minutes * 60.0
    return max(0.0, free_seconds - used)


async def _update_usage(
    db: AsyncSession, identity_id: str, duration_seconds: float, cost_cents: int
) -> None:
    """Increment monthly compute usage."""
    month = _current_month()
    result = await db.execute(
        select(ComputeUsageRecord).where(
            ComputeUsageRecord.identity_id == identity_id,
            ComputeUsageRecord.month == month,
        )
    )
    record = result.scalar_one_or_none()
    if record:
        record.total_seconds += duration_seconds
        record.total_jobs += 1
        record.total_cost_cents += cost_cents
    else:
        record = ComputeUsageRecord(
            identity_id=identity_id,
            month=month,
            total_seconds=duration_seconds,
            total_jobs=1,
            total_cost_cents=cost_cents,
        )
        db.add(record)


@router.post("/stt", response_model=TranscriptionResult)
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    model: str = Form("large-v3"),
    # Paid GPU path — gate on the write-path trust check (403 for a
    # frozen/revoked identity; fail-closed 503 if Trust is unreachable),
    # matching servers.py POST /create. A suspended agent must not burn
    # compute during an Eternitas outage.
    user: AuthenticatedUser = Depends(require_not_blocked_for_write),
    db: AsyncSession = Depends(get_db),
):
    provider = _get_stt_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STT compute is not configured. Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID.",
        )

    # Chunked read — raises 413 mid-stream if max_upload_size is exceeded.
    audio = await read_bounded(file, settings.max_upload_size)
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # Create job record
    job = ComputeJob(
        identity_id=user.identity_id,
        model=model,
        language=language,
        status="processing",
    )
    db.add(job)
    await db.flush()

    # Run transcription
    result = await provider.transcribe(audio, language=language, model=model)
    result.job_id = job.id

    # Apply free tier
    free_remaining = await _get_free_seconds_remaining(db, user.identity_id)
    actual_cost = result.cost_cents
    if result.duration_seconds and free_remaining > 0:
        free_covered = min(result.duration_seconds, free_remaining)
        billable_seconds = max(0, result.duration_seconds - free_covered)
        if billable_seconds == 0:
            actual_cost = 0
        else:
            ratio = billable_seconds / result.duration_seconds
            actual_cost = max(0, round(result.cost_cents * ratio))
        result.cost_cents = actual_cost

    # Update job record
    job.status = result.status
    job.audio_duration_seconds = result.duration_seconds or 0.0
    job.result_text = result.text
    if result.segments:
        job.result_segments_json = json.dumps([s.model_dump() for s in result.segments])
    job.cost_cents = actual_cost
    job.error = result.error
    if result.status in ("completed", "failed"):
        job.completed_at = datetime.now(timezone.utc)

    # Update usage
    if result.status == "completed" and result.duration_seconds:
        await _update_usage(db, user.identity_id, result.duration_seconds, actual_cost)

    await db.commit()
    return result


@router.get("/stt/{job_id}", response_model=STTJobStatus)
async def get_stt_job(
    job_id: str,
    user: AuthenticatedUser = Depends(require_not_frozen),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ComputeJob).where(
            ComputeJob.id == job_id,
            ComputeJob.identity_id == user.identity_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stt_result = None
    if job.status == "completed":
        segments = []
        if job.result_segments_json:
            segments_data = json.loads(job.result_segments_json)
            segments = [TranscriptionSegment(**s) for s in segments_data]

        stt_result = TranscriptionResult(
            job_id=job.id,
            status=job.status,
            text=job.result_text,
            segments=segments,
            language=job.language,
            duration_seconds=job.audio_duration_seconds,
            cost_cents=job.cost_cents,
        )

    return STTJobStatus(
        job_id=job.id,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        result=stt_result,
    )


@router.get("/usage", response_model=ComputeUsageResponse)
async def compute_usage(
    user: AuthenticatedUser = Depends(require_not_frozen),
    db: AsyncSession = Depends(get_db),
):
    month = _current_month()
    result = await db.execute(
        select(ComputeUsageRecord).where(
            ComputeUsageRecord.identity_id == user.identity_id,
            ComputeUsageRecord.month == month,
        )
    )
    record = result.scalar_one_or_none()

    total_seconds = record.total_seconds if record else 0.0
    total_jobs = record.total_jobs if record else 0
    total_cost = record.total_cost_cents if record else 0
    free_seconds = settings.stt_free_minutes * 60.0
    free_remaining = max(0.0, free_seconds - total_seconds) / 60.0

    return ComputeUsageResponse(
        identity_id=user.identity_id,
        month=month,
        total_seconds=total_seconds,
        total_jobs=total_jobs,
        total_cost_cents=total_cost,
        free_minutes_remaining=round(free_remaining, 2),
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models():
    provider = _get_stt_provider()
    pricing = provider.pricing() if provider else {}
    cost = pricing.get("cost_per_minute_cents", 3.0)

    return ModelsResponse(
        models=[
            ModelInfo(
                model_id="large-v3",
                name="Whisper Large V3",
                description="Best accuracy, GPU-accelerated via faster-whisper",
                cost_per_minute_cents=cost,
            ),
            ModelInfo(
                model_id="medium",
                name="Whisper Medium",
                description="Good accuracy, faster processing",
                cost_per_minute_cents=round(cost * 0.6, 2),
            ),
            ModelInfo(
                model_id="small",
                name="Whisper Small",
                description="Fast processing, acceptable accuracy",
                cost_per_minute_cents=round(cost * 0.3, 2),
            ),
        ],
        free_minutes_per_month=settings.stt_free_minutes,
    )
