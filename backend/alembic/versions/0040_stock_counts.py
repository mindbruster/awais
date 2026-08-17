"""Counting the safe, and what to do when it disagrees with the books.

The one thing a precious-metals system must be able to do is compare what it
*says* is there with what is actually on the scale — and this one could not.
Stock only ever moved through documents, which is the right rule and is exactly
why a discrepancy had nowhere to go: there was no document for "we weighed it
and there is 2.6 g less than there should be".

The temptation is an editable stock figure. That is the one thing this system
has refused everywhere else and refuses here: a count does not overwrite a
balance, it **posts a movement and a journal entry** like every other change,
carrying a reason and a name. The count sheet is the source document.

**The book figure is frozen when the sheet is opened**, not read again at
posting time. A count that took an hour while the counter was still selling
would otherwise produce a variance made partly of real sales, and the shop
would go looking for metal that had walked out of the door legitimately.

**5500 Stock Variance** is one account swinging both ways rather than a
shrinkage head and a windfall head. It is one phenomenon — the count did not
match — and splitting it would make a month containing both a loss on gold and
a gain on silver read as two unrelated events instead of one stock-take.

A credit balance on it is worth a hard look: finding *more* metal than the books
show does not mean the shop got richer, it means something arrived that was
never recorded.

Revision ID: 0040_stock_counts
Revises: 0039_vendor_due
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Created by 0027 for job legs. Referenced, never redefined — `sa.Enum` would
# emit a CREATE TYPE for a type that already exists and fail the migration.
METAL = postgresql.ENUM("gold", "silver", name="metal", create_type=False)

revision: str = "0040_stock_counts"
down_revision: Union[str, None] = "0039_vendor_due"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO accounts
                (code, name, type, parent_id, is_system, is_postable, is_active)
            VALUES (
                '5500', 'Stock Variance', CAST('expense' AS account_type),
                (SELECT id FROM accounts WHERE code = '5000'),
                TRUE, TRUE, TRUE
            )
            ON CONFLICT (code) DO NOTHING
            """
        )
    )

    op.create_table(
        "stock_counts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("count_no", sa.String(length=50), nullable=False),
        # Which safe was counted. A count is always of one branch's stock —
        # weighing Anarkali and adjusting Gulberg is how both end up wrong.
        sa.Column(
            "branch_id",
            sa.Integer(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("metal", METAL, nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "posted", "cancelled", name="stock_count_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=False),
        # Why the shop is counting — "month end", "after the Eid rush". Not the
        # reason for the variance; that is per posting and is required there.
        sa.Column("notes", sa.Text(), nullable=True),
        # Required to post. A variance with no explanation is the thing an
        # auditor asks about first, so the system asks first instead.
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "journal_entry_id",
            sa.Integer(),
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Held apart from the creator on purpose: counting and accepting a
        # write-off are different acts, and a shop that wants two people on them
        # can now see whether it got two.
        sa.Column(
            "posted_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_stock_counts_count_no", "stock_counts", ["count_no"], unique=True)
    op.create_index("ix_stock_counts_branch_id", "stock_counts", ["branch_id"])
    op.create_index("ix_stock_counts_status", "stock_counts", ["status"])

    op.create_table(
        "stock_count_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "count_id",
            sa.Integer(),
            sa.ForeignKey("stock_counts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inventory_item_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # What the books said when the sheet was opened. Frozen deliberately —
        # see the module docstring.
        sa.Column("book_weight_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        # What was actually on the scale. NULL means this pot has not been
        # weighed yet, which is not the same as weighing zero — and treating it
        # as zero would write the whole pot off.
        sa.Column("counted_weight_g", sa.Numeric(14, 4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_stock_count_lines_count_id", "stock_count_lines", ["count_id"])
    op.create_unique_constraint(
        "uq_stock_count_line_item", "stock_count_lines", ["count_id", "inventory_item_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_stock_count_line_item", "stock_count_lines", type_="unique")
    op.drop_index("ix_stock_count_lines_count_id", table_name="stock_count_lines")
    op.drop_table("stock_count_lines")
    op.drop_index("ix_stock_counts_status", table_name="stock_counts")
    op.drop_index("ix_stock_counts_branch_id", table_name="stock_counts")
    op.drop_index("ix_stock_counts_count_no", table_name="stock_counts")
    op.drop_table("stock_counts")
    op.execute(sa.text("DROP TYPE IF EXISTS stock_count_status"))
    # An account that has been posted to stays: dropping it would orphan the
    # lines holding a real write-off.
    op.execute(
        """
        DELETE FROM accounts
        WHERE code = '5500'
          AND NOT EXISTS (SELECT 1 FROM journal_lines WHERE account_id = accounts.id)
        """
    )
