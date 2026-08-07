"""Migrate tier vocabulary to the ecosystem canon and reprice quotas.

Until 2026-08-07 this repo used `free / pro / ultra / max` as canonical tier
ids with its own private quota ladder (5 GB / 100 GB / 1 TB / 5 TB). Every
other Windy product uses `free / pro / translate / translate_pro` as the
DATABASE ids, with "Ultra" and "Max" as display names only — so `ultra` and
`max` meant one thing here and another everywhere else, and the two ladders
disagreed by up to 170x.

The ecosystem contract (windy-pro/docs/PRICING-TIERS.md, amended 2026-08-07):

    free           500 MB
    pro            5 GB      Windy Pro
    translate      25 GB     Windy Ultra
    translate_pro  100 GB    Windy Max
    tempest        1 TB
    tornado        2 TB
    hurricane      5 TB floor, sold per contract

Row mapping. `ultra` -> `translate` and `max` -> `translate_pro` are pure
renames of the same rung. Quotas are NOT rewritten wholesale: this migration
only lowers a row to the new ladder when that row still holds the exact old
default, so anyone with a hand-granted or trust-multiplied quota keeps it.
Nothing is ever lowered below what the account server later pushes, because
/billing/allocate overwrites quota_bytes with the authoritative number.

Safety at the time of writing: all 76 rows in production were `free` bot
accounts holding 18.6 MB across 27 files, so no real customer is affected.

Revision ID: 006
Revises: 005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels = None
depends_on = None

# old id -> new id
RENAMES: list[tuple[str, str]] = [
    ("ultra", "translate"),
    ("max", "translate_pro"),
]

# new id -> (old default quota, new contract quota).
# A row is repriced ONLY if it still holds the old default exactly.
REPRICE: list[tuple[str, int, int]] = [
    ("free", 5_368_709_120, 524_288_000),               # 5 GB    -> 500 MB
    ("pro", 107_374_182_400, 5_368_709_120),            # 100 GB  -> 5 GB
    ("translate", 1_099_511_627_776, 26_843_545_600),   # 1 TB    -> 25 GB
    ("translate_pro", 5_497_558_138_880, 107_374_182_400),  # 5 TB -> 100 GB
]


def upgrade() -> None:
    conn = op.get_bind()

    # Rename first so the reprice step sees canonical ids.
    for old, new in RENAMES:
        for column in ("tier", "plan_id"):
            conn.execute(
                sa.text(
                    f"UPDATE user_plans SET {column} = :new WHERE {column} = :old"
                ),
                {"old": old, "new": new},
            )

    for tier, old_quota, new_quota in REPRICE:
        conn.execute(
            sa.text(
                "UPDATE user_plans SET quota_bytes = :new_quota "
                "WHERE tier = :tier AND quota_bytes = :old_quota"
            ),
            {"tier": tier, "old_quota": old_quota, "new_quota": new_quota},
        )


def downgrade() -> None:
    conn = op.get_bind()

    for tier, old_quota, new_quota in REPRICE:
        conn.execute(
            sa.text(
                "UPDATE user_plans SET quota_bytes = :old_quota "
                "WHERE tier = :tier AND quota_bytes = :new_quota"
            ),
            {"tier": tier, "old_quota": old_quota, "new_quota": new_quota},
        )

    # tempest/tornado/hurricane have no pre-006 equivalent; collapse them to
    # the old top rung rather than leaving ids the old code would reject.
    for column in ("tier", "plan_id"):
        conn.execute(
            sa.text(
                f"UPDATE user_plans SET {column} = 'max' "
                f"WHERE {column} IN ('tempest', 'tornado', 'hurricane')"
            )
        )
        for old, new in RENAMES:
            conn.execute(
                sa.text(
                    f"UPDATE user_plans SET {column} = :old WHERE {column} = :new"
                ),
                {"old": old, "new": new},
            )
