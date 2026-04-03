"""Initial schema — all tables for storage, compute, billing, and servers.

Revision ID: 001
Revises: None
Create Date: 2026-04-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_id", sa.String(36), nullable=False, index=True),
        sa.Column("product", sa.String(50), nullable=False, index=True),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("storage_key", sa.String(1000), nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("content_type", sa.String(200), server_default="application/octet-stream"),
        sa.Column("encrypted", sa.Boolean, server_default=sa.text("0")),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("retention_count", sa.Integer, nullable=True),
        sa.Column("retention_days", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_files_identity_product", "files", ["identity_id", "product"])
    op.create_index(
        "ix_files_identity_product_type", "files", ["identity_id", "product", "file_type"]
    )

    op.create_table(
        "usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_id", sa.String(36), nullable=False, index=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("storage_bytes", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("file_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("upload_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("download_count", sa.Integer, server_default=sa.text("0")),
    )
    op.create_index("ix_usage_identity_month", "usage", ["identity_id", "month"], unique=True)

    op.create_table(
        "compute_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(20), server_default="processing"),
        sa.Column("model", sa.String(50), server_default="large-v3"),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("audio_duration_seconds", sa.Float, server_default=sa.text("0.0")),
        sa.Column("result_text", sa.Text, nullable=True),
        sa.Column("result_segments_json", sa.Text, nullable=True),
        sa.Column("cost_cents", sa.Integer, server_default=sa.text("0")),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_compute_jobs_identity", "compute_jobs", ["identity_id"])

    op.create_table(
        "compute_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_id", sa.String(36), nullable=False, index=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("total_seconds", sa.Float, server_default=sa.text("0.0")),
        sa.Column("total_jobs", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_cost_cents", sa.Integer, server_default=sa.text("0")),
    )
    op.create_index(
        "ix_compute_usage_identity_month", "compute_usage", ["identity_id", "month"], unique=True
    )

    op.create_table(
        "servers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_id", sa.String(36), nullable=False, index=True),
        sa.Column("plan_id", sa.String(50), nullable=False),
        sa.Column("region", sa.String(50), nullable=False),
        sa.Column("image", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), server_default="provisioning"),
        sa.Column("provider_instance_id", sa.String(100), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("hostname", sa.String(200), nullable=True),
        sa.Column("monthly_cost_cents", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_servers_identity", "servers", ["identity_id"])

    op.create_table(
        "billing_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identity_id", sa.String(36), nullable=False, index=True),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("storage_bytes", sa.BigInteger, server_default=sa.text("0")),
        sa.Column("file_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("compute_seconds", sa.Float, server_default=sa.text("0.0")),
        sa.Column("compute_cost_cents", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_billing_snapshots_identity_date",
        "billing_snapshots",
        ["identity_id", "date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("billing_snapshots")
    op.drop_table("servers")
    op.drop_table("compute_usage")
    op.drop_table("compute_jobs")
    op.drop_table("usage")
    op.drop_table("files")
