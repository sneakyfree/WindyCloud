"""Pydantic models for billing API."""

from __future__ import annotations

from pydantic import BaseModel


class StorageUsageSummary(BaseModel):
    used_bytes: int
    file_count: int
    quota_bytes: int


class ComputeUsageSummary(BaseModel):
    total_seconds: float
    total_jobs: int
    total_cost_cents: int


class BillingUsageResponse(BaseModel):
    identity_id: str
    month: str
    storage: StorageUsageSummary
    compute: ComputeUsageSummary
    total_cost_cents: int


class BillingHistoryEntry(BaseModel):
    month: str
    storage_bytes: int
    compute_seconds: float
    compute_cost_cents: int
    total_cost_cents: int


class BillingHistoryResponse(BaseModel):
    entries: list[BillingHistoryEntry]


class BillingEstimateResponse(BaseModel):
    month: str
    storage_cost_cents: int
    compute_cost_cents: int
    total_estimated_cents: int
