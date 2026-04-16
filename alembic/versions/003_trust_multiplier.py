"""Wave 3 — record trust multiplier at plan allocation for audit.

Revision ID: 003
Revises: 002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "user_plans" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("user_plans")}
        if "trust_multiplier_at_allocation" not in cols:
            op.add_column(
                "user_plans",
                sa.Column("trust_multiplier_at_allocation", sa.Float, nullable=True),
            )


def downgrade() -> None:
    with op.batch_alter_table("user_plans") as batch:
        batch.drop_column("trust_multiplier_at_allocation")
