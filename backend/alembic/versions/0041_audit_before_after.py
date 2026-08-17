"""An audit line should say what the value *was*, not only that it changed.

`audit_log` recorded who, what, when and a free-form `details` blob. Whether a
line carried the old value depended entirely on what the call site happened to
put in that blob, and most put nothing — so the log could tell you that Abdul
edited a gold rate and not what it had been.

That is the difference between a log and an audit trail. "Rate changed" is a
notification; "rate changed from 99,999 to 9,999" is evidence.

Three columns rather than one:

* **`before` / `after`** hold *only the fields that differed*, not whole rows.
  A full snapshot of both sides buries the one changed number in forty
  unchanged ones, and on a wide table it makes the log larger than the data.
* **`reason`** is its own column because it is the field somebody actually
  searches, and burying it in JSON means it cannot be indexed or filtered.

`details` stays. It carries the things that are not field changes — how many
lots were on a bill, which entry a reversal produced — and rewriting every
existing call site to fit a before/after shape would lose information that is
genuinely not a diff.

Revision ID: 0041_audit_diff
Revises: 0040_stock_counts
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_audit_diff"
down_revision: Union[str, None] = "0040_stock_counts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("before", postgresql.JSONB(), nullable=True))
    op.add_column("audit_log", sa.Column("after", postgresql.JSONB(), nullable=True))
    op.add_column("audit_log", sa.Column("reason", sa.Text(), nullable=True))
    # Existing rows keep NULL rather than being backfilled with `{}`. An empty
    # object would claim "nothing changed" about actions that were never
    # recorded that way; NULL says "not captured", which is the truth.


def downgrade() -> None:
    op.drop_column("audit_log", "reason")
    op.drop_column("audit_log", "after")
    op.drop_column("audit_log", "before")
