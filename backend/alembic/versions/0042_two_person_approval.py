"""Counting the metal and accepting the loss should be two people.

`stock_counts` already recorded `created_by_user_id` and `posted_by_user_id`
separately, so a shop could *see* whether two people were involved. Nothing
required it, and nothing gave the second person a queue to work from — the
approver had no way to know a sheet was waiting.

Two changes:

**A `submitted` state.** Draft means somebody is still weighing; submitted means
the counting is finished and a decision is wanted. Without it there is no
difference between a sheet half-filled and one ready to sign, and the approver
would have to guess.

**`submitted_by_user_id` / `submitted_at`.** The creator opened the sheet; the
submitter is the one asserting the figures are what the scale said. Usually the
same person, not always — a sheet opened in the morning and finished by whoever
is on shift at six is normal — and the check is against whoever *asserted* the
numbers, not whoever clicked "new".

Whether the two must differ is a policy, not a schema question, so it lives in
configuration: `REQUIRE_TWO_PERSON_APPROVAL`. Off by default, because a shop
with one admin would otherwise be unable to post a count at all, which is worse
than the risk it guards against.

Revision ID: 0042_two_person
Revises: 0041_audit_diff
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_two_person"
down_revision: Union[str, None] = "0041_audit_diff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `IF NOT EXISTS` so a database that has already been repaired by hand does
    # not fail the migration, matching how every other enum here is extended.
    op.execute("ALTER TYPE stock_count_status ADD VALUE IF NOT EXISTS 'submitted'")

    op.add_column(
        "stock_counts",
        sa.Column(
            "submitted_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "stock_counts",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_counts", "submitted_at")
    op.drop_column("stock_counts", "submitted_by_user_id")
    # The enum value stays. Postgres cannot drop one, and any sheet already in
    # `submitted` would become unreadable if it could.
