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


class BillingSyncRequest(BaseModel):
    windy_identity_id: str


class BillingSyncResponse(BaseModel):
    identity_id: str
    month: str
    storage_bytes: int
    storage_file_count: int
    compute_minutes: float
    compute_cost_cents: int
    server_count: int
    server_monthly_cost_cents: int
    total_cost_cents: int


class BillingSummaryResponse(BaseModel):
    identity_id: str
    storage_used: str
    storage_quota: str
    storage_percent: float
    compute_minutes_used: float
    compute_free_remaining: float
    total_cost_cents: int
