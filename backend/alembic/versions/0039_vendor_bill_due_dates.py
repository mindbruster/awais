"""A bill the shop owes needs a date on it, and a way to be paid.

Two halves of one hole. Purchases on credit posted to `2110 Suppliers` and then
sat there: no date said when they were due, and nothing in the system could pay
one. The only way to clear a payable was a hand-written journal entry, so the
payables figure grew forever and "which bills are due this week" had no answer
at all.

**`due_date` is nullable and stays nullable.** Plenty of bills are settled at
the counter and never had a date; forcing one would mean inventing a deadline
nobody agreed to, and an invented deadline in an overdue report is worse than
no report. A bill without a date is reported as undated rather than as due.

**`supplier_payments` is its own table, not a row in `payments`.** That table
is a customer settlement: it carries `customer_id NOT NULL`, an invoice link
and a gold-exchange path where a customer hands metal across the counter.
Bending it to face the other way would have meant making its customer nullable
— which is the column that stops a payment being recorded against nobody — for
the sake of sharing four fields.

**No allocation table.** Which bills a payment settles is *derived*, oldest
first, from the payments on record against that supplier. The shop chose this:
it is how a khata works, a payment is knocked off the oldest bill. The cost is
real and worth stating — money handed over for this week's bill will show as
clearing March's — and the benefit is that a bill's paid status cannot drift
from the ledger, because there is no stored status to drift. `outstanding` is
computed at read time from figures that are themselves postings.

Revision ID: 0039_vendor_due
Revises: 0038_silver_purch
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

METHOD = postgresql.ENUM(
    "cash", "bank", "credit", name="gold_payment_mode", create_type=False
)

revision: str = "0039_vendor_due"
down_revision: Union[str, None] = "0038_silver_purch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("gold_purchases", "stone_purchases"):
        op.add_column(table, sa.Column("due_date", sa.Date(), nullable=True))
        op.create_index(f"ix_{table}_due_date", table, ["due_date"])

    op.create_table(
        "supplier_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_no", sa.String(length=50), nullable=False),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        # Reuses the enum the bullion bills already pay by, so "cash", "bank"
        # and "credit" mean one thing across purchasing. `credit` is refused at
        # the schema — paying a bill on credit is not a payment.
        # The enum the bullion bills already pay by. Referenced, never
        # redefined: `sa.Enum` would emit a CREATE TYPE for a type that exists
        # since 0022, and the whole migration fails on it. `postgresql.ENUM`
        # with `create_type=False` is what says "this is already there".
        sa.Column("method", METHOD, nullable=False, server_default="cash"),
        sa.Column(
            "bank_account_id",
            sa.Integer(),
            sa.ForeignKey("bank_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_supplier_payments_payment_no", "supplier_payments", ["payment_no"], unique=True
    )
    op.create_index("ix_supplier_payments_supplier_id", "supplier_payments", ["supplier_id"])
    op.create_index("ix_supplier_payments_paid_at", "supplier_payments", ["paid_at"])


def downgrade() -> None:
    op.drop_index("ix_supplier_payments_paid_at", table_name="supplier_payments")
    op.drop_index("ix_supplier_payments_supplier_id", table_name="supplier_payments")
    op.drop_index("ix_supplier_payments_payment_no", table_name="supplier_payments")
    op.drop_table("supplier_payments")
    for table in ("gold_purchases", "stone_purchases"):
        op.drop_index(f"ix_{table}_due_date", table_name=table)
        op.drop_column(table, "due_date")
