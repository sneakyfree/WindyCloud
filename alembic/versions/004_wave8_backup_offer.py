"""Wave 8 — backup offer idempotency table.

Revision ID: 004
Revises: 003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "backup_offers" not in insp.get_table_names():
        op.create_table(
            "backup_offers",
            sa.Column("identity_id", sa.String(36), primary_key=True),
            sa.Column("recording_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bytes_estimated", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column(
                "notification_sent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "notification_sent_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    op.drop_table("backup_offers")
