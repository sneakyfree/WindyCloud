"""Pydantic models for compute (STT) API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResult(BaseModel):
    job_id: str
    status: str = "completed"  # "processing", "completed", "failed"
    text: str | None = None
    segments: list[TranscriptionSegment] = []
    language: str | None = None
    duration_seconds: float | None = None
    cost_cents: int = 0
    error: str | None = None


class STTJobStatus(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    result: TranscriptionResult | None = None


class ModelInfo(BaseModel):
    model_id: str
    name: str
    description: str
    cost_per_minute_cents: float


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    free_minutes_per_month: int


class ComputeUsageResponse(BaseModel):
    identity_id: str
    month: str
    total_seconds: float
    total_jobs: int
    total_cost_cents: int
    free_minutes_remaining: float
