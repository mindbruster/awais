"""The cash book: money in and out that no other document explains.

Everything else in this system moves cash as a *consequence* of a document — an
invoice bills, a payment settles, a purchase owes. What had nowhere to go was
the ordinary day: rent, wages, the electricity bill, a courier, tea, the owner
putting a few thousand into the till. None of it reached the books, so the cash
figure on the dashboard was only ever the part of the shop's money that happened
to pass through a sale, and "where did today's money go" was a question the
system could not answer at all.

`cash_entries` records those movements and posts a balanced journal entry for
each, so cash and bank balances stay derived from the ledger rather than from a
column somebody has to remember to update.

`cash_categories` is the shop's own list of headings — editable, because every
shop's list is different and a fixed enum would mean a code change to record a
kind of expense the shop already has. What is not editable from the counter is
which ledger head a category posts to: that is a chart-of-accounts decision, and
letting it be repointed would silently restate history. A category naming no
account falls back to 5300 Other Expenses or 4400 Other Income, which is honest
rather than precise and better than refusing to record money because nobody has
set up a chart yet.

**4400 Other Income** is new. Money in that is not a sale — capital into the
till, a supplier refund, scrap sold off the bench — needed a head of its own, or
revenue stops meaning revenue and a margin report counts the owner topping up
the drawer as a month's trading.

Cash and bank stay apart throughout. A drawer is counted and a bank account is
agreed against a statement; one "money" figure covering both cannot be
reconciled against either.

Revision ID: 0033_cash_book
Revises: 0032_stone_fifo
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_cash_book"
down_revision: Union[str, None] = "0032_stone_fifo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

cash_direction = postgresql.ENUM("paid", "received", name="cash_direction", create_type=False)
cash_method = postgresql.ENUM("cash", "bank", name="cash_method", create_type=False)

NEW_ACCOUNTS = [
    ("4400", "Other Income", "income", "4000"),
]


def upgrade() -> None:
    bind = op.get_bind()
    cash_direction.create(bind, checkfirst=True)
    cash_method.create(bind, checkfirst=True)

    op.create_table(
        "cash_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        # Null means the heading works either way — "bank charges" is only ever
        # paid, but "adjustment" goes both directions.
        sa.Column("direction", cash_direction, nullable=True),
        sa.Column("account_code", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_cash_categories_name"),
    )
    op.create_index("ix_cash_categories_name", "cash_categories", ["name"])
    op.create_index("ix_cash_categories_direction", "cash_categories", ["direction"])
    op.create_index("ix_cash_categories_account_code", "cash_categories", ["account_code"])
    op.create_index("ix_cash_categories_is_active", "cash_categories", ["is_active"])

    op.create_table(
        "cash_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_no", sa.String(50), nullable=False),
        sa.Column("direction", cash_direction, nullable=False),
        sa.Column("method", cash_method, nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        # The day the money moved, not the day it was keyed. A cash book filed
        # by typing date cannot be reconciled against a drawer count.
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("currency", postgresql.ENUM(name="currency", create_type=False),
                  nullable=False, server_default="PKR"),
        sa.Column("fx_rate_to_pkr", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("counterparty", sa.String(150), nullable=True),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("entry_no", name="uq_cash_entries_entry_no"),
        # RESTRICT throughout: a category, account or entry that has money
        # filed against it is part of the shop's history, and deleting it would
        # leave a posting nobody can explain.
        sa.ForeignKeyConstraint(["category_id"], ["cash_categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    for col in ("entry_no", "direction", "method", "category_id", "occurred_on",
                "bank_account_id", "counterparty", "branch_id", "journal_entry_id"):
        op.create_index(f"ix_cash_entries_{col}", "cash_entries", [col])

    for code, name, type_, parent_code in NEW_ACCOUNTS:
        op.execute(
            sa.text(
                """
                INSERT INTO accounts
                    (code, name, type, parent_id, is_system, is_postable, is_active)
                VALUES (
                    :code, :name, CAST(:type AS account_type),
                    (SELECT id FROM accounts WHERE code = :parent_code),
                    TRUE, TRUE, TRUE
                )
                ON CONFLICT (code) DO NOTHING
                """
            ).bindparams(code=code, name=name, type=type_, parent_code=parent_code)
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM accounts
        WHERE code = '4400'
          AND NOT EXISTS (SELECT 1 FROM journal_lines WHERE account_id = accounts.id)
        """
    )
    op.drop_table("cash_entries")
    op.drop_table("cash_categories")
    cash_method.drop(op.get_bind(), checkfirst=True)
    cash_direction.drop(op.get_bind(), checkfirst=True)
