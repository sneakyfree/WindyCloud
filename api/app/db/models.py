"""ORM models for file metadata and usage tracking."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FileRecord(Base):
    """Metadata for every file stored in Cloud."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    identity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_files_identity_product", "identity_id", "product"),
        Index("ix_files_identity_product_type", "identity_id", "product", "file_type"),
    )


class UsageRecord(Base):
    """Monthly usage tracking per identity."""

    __tablename__ = "usage"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    identity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)  # "2026-04"
    storage_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    upload_count: Mapped[int] = mapped_column(Integer, default=0)
    download_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_usage_identity_month", "identity_id", "month", unique=True),
    )


class ComputeJob(Base):
    """Individual STT compute job."""

    __tablename__ = "compute_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    identity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing/completed/failed
    model: Mapped[str] = mapped_column(String(50), default="large-v3")
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    audio_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_segments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_compute_jobs_identity", "identity_id"),
    )


class ComputeUsageRecord(Base):
    """Monthly compute usage tracking per identity."""

    __tablename__ = "compute_usage"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    identity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    total_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_cents: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_compute_usage_identity_month", "identity_id", "month", unique=True),
    )


class ServerRecord(Base):
    """VPS server instance metadata."""

    __tablename__ = "servers"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    identity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    region: Mapped[str] = mapped_column(String(50), nullable=False)
    image: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="provisioning")
    provider_instance_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(200), nullable=True)
    monthly_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_servers_identity", "identity_id"),
    )
