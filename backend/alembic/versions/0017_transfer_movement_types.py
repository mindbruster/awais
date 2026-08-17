"""Name a branch transfer for what it is.

`stock_movement_type` had no value for stock moving between two of the shop's own
counters, which left `adjustment` as the only fit. That reads as a correction:
a stock report would show every transfer as an unexplained write-off at the
sending branch and a windfall at the receiving one, and the two would never be
recognisable as the same event.

Postgres enum values cannot be dropped, so this migration has no meaningful
downgrade — the values are simply left in place, which is harmless.

Revision ID: 0017_transfer_movements
Revises: 0016_branches
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0017_transfer_movements"
down_revision: Union[str, None] = "0016_branches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS so a re-run is safe; ALTER TYPE ... ADD VALUE cannot run
    # inside a transaction block on older Postgres, but is permitted from 12 on,
    # which is well below the 16 this project targets.
    op.execute("ALTER TYPE stock_movement_type ADD VALUE IF NOT EXISTS 'transfer_out'")
    op.execute("ALTER TYPE stock_movement_type ADD VALUE IF NOT EXISTS 'transfer_in'")


def downgrade() -> None:
    # Postgres offers no DROP VALUE. Leaving the labels in place is harmless:
    # nothing writes them once the transfer feature is gone.
    pass
