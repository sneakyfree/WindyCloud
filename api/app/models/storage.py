"""Pydantic request/response models for storage API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# --- Responses ---


class FileInfo(BaseModel):
    file_id: str
    product: str
    file_type: str
    filename: str
    storage_key: str
    size_bytes: int
    content_type: str
    encrypted: bool = False
    created_at: datetime


class UploadResponse(BaseModel):
    file_id: str
    key: str
    size: int
    content_type: str
    message: str = "File uploaded successfully"


class FileListResponse(BaseModel):
    files: list[FileInfo]
    total: int
    next_token: str | None = None
    truncated: bool = False


class UsageResponse(BaseModel):
    used_bytes: int
    file_count: int
    quota_bytes: int
    used_percent: float


class DeleteResponse(BaseModel):
    deleted: bool
    file_id: str
    message: str = "File deleted"


# --- Archive ---


class ArchiveRequest(BaseModel):
    """Common fields for product archive uploads (sent as form metadata JSON)."""

    product: str
    type: str
    encrypted: bool = False
    retention_count: int | None = None
    retention_days: int | None = None
    agent_name: str | None = None
    passport_id: str | None = None
    duration: int | None = None
    format: str | None = None
    sync: bool = False


class ArchiveResponse(BaseModel):
    file_id: str
    key: str
    product: str
    type: str
    size: int
    message: str = "Archive stored successfully"
