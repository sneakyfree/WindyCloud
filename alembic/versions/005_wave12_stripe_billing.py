"""Wave 12 C-2 — Stripe billing columns on user_plans + webhook_deliveries.

Revision ID: 005
Revises: 004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if "user_plans" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("user_plans")}
        if "billing_status" not in cols:
            op.add_column(
                "user_plans",
                sa.Column(
                    "billing_status",
                    sa.String(length=20),
                    nullable=False,
                    server_default="active",
                ),
            )
        if "stripe_customer_id" not in cols:
            op.add_column(
                "user_plans",
                sa.Column("stripe_customer_id", sa.String(length=64), nullable=True),
            )
        if "stripe_subscription_id" not in cols:
            op.add_column(
                "user_plans",
                sa.Column(
                    "stripe_subscription_id", sa.String(length=64), nullable=True
                ),
            )
        existing_indexes = {ix["name"] for ix in insp.get_indexes("user_plans")}
        if "ix_user_plans_stripe_customer" not in existing_indexes:
            op.create_index(
                "ix_user_plans_stripe_customer",
                "user_plans",
                ["stripe_customer_id"],
            )

    if "webhook_deliveries" not in insp.get_table_names():
        op.create_table(
            "webhook_deliveries",
            sa.Column("provider", sa.String(length=20), primary_key=True),
            sa.Column("event_id", sa.String(length=128), primary_key=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_webhook_deliveries_received",
            "webhook_deliveries",
            ["provider", "received_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_received", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    with op.batch_alter_table("user_plans") as batch:
        batch.drop_index("ix_user_plans_stripe_customer")
        batch.drop_column("stripe_subscription_id")
        batch.drop_column("stripe_customer_id")
        batch.drop_column("billing_status")
