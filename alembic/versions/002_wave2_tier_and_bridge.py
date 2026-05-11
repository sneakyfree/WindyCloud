"""Wave 2 — tier+frozen on user_plans and passport↔identity bridge.

Adds the schema needed for contracts #1 (tier allocation), #2 (passport
revocation freeze) and #3 (passport↔identity bridge).

The 001 migration never created `user_plans` — it was being built at
runtime via Base.metadata.create_all. This migration backfills that gap
so alembic becomes authoritative, while staying idempotent for
deployments where the table already exists.

Revision ID: 002
Revises: 001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    if "user_plans" not in existing_tables:
        op.create_table(
            "user_plans",
            sa.Column("identity_id", sa.String(36), primary_key=True),
            sa.Column("plan_id", sa.String(20), server_default="free", nullable=False),
            sa.Column("tier", sa.String(20), server_default="free", nullable=False),
            sa.Column("quota_bytes", sa.BigInteger, server_default=sa.text("5368709120")),
            sa.Column(
                "frozen", sa.Boolean, server_default=sa.text("false"), nullable=False
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    else:
        existing_cols = {c["name"] for c in insp.get_columns("user_plans")}
        if "tier" not in existing_cols:
            op.add_column(
                "user_plans",
                sa.Column(
                    "tier", sa.String(20), server_default="free", nullable=False
                ),
            )
        if "frozen" not in existing_cols:
            op.add_column(
                "user_plans",
                sa.Column(
                    "frozen", sa.Boolean, server_default=sa.text("false"), nullable=False
                ),
            )

    if "users_identity_bridge" not in existing_tables:
        op.create_table(
            "users_identity_bridge",
            sa.Column("windy_identity_id", sa.String(36), primary_key=True),
            sa.Column("passport_number", sa.String(64), nullable=False),
            sa.Column("operator_email", sa.String(320), nullable=True),
            sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("linked_by", sa.String(100), nullable=True),
        )
        op.create_index(
            "ix_identity_bridge_passport",
            "users_identity_bridge",
            ["passport_number"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("ix_identity_bridge_passport", table_name="users_identity_bridge")
    op.drop_table("users_identity_bridge")
    with op.batch_alter_table("user_plans") as batch:
        batch.drop_column("frozen")
        batch.drop_column("tier")
