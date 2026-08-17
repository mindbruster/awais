"""Buying raw gold from a dealer.

Metal could only get into the melt pot two ways: a customer walking in with old
jewellery, or gold handed over to settle a bill. Both are the shop *receiving*
metal from the public. Neither is how a workshop actually stocks up — it buys
bullion from a dealer, on a bill, often on credit.

The gap was not cosmetic. A dealer's bill recorded as an old-gold buy-back
would have been priced against the "we buy below the day's rate" rule that
exists to protect the buy-back margin, paid in cash it was not paid in, and
filed against a customer who was never involved. Metal taken on account would
not have appeared as a payable at all: the shop would owe a dealer half a kilo
of money with nothing on the books saying so.

`suppliers` is reused rather than duplicated. It already models "a party the
shop owes money to for goods", which is exactly what a bullion dealer is.

Revision ID: 0024_gold_purchases
Revises: 0023_invoice_terms
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_gold_purchases"
down_revision: Union[str, None] = "0023_invoice_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODES = ("cash", "bank", "credit")


def upgrade() -> None:
    # Create the type once, explicitly, then reference it with create_type=False
    # so create_table does not try to emit CREATE TYPE a second time.
    sa.Enum(*_MODES, name="gold_payment_mode").create(op.get_bind(), checkfirst=True)
    mode = postgresql.ENUM(*_MODES, name="gold_payment_mode", create_type=False)
    # `currency` already exists — every money table references it.
    currency = postgresql.ENUM(name="currency", create_type=False)

    op.create_table(
        "gold_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_no", sa.String(50), nullable=False),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.Integer(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("payment_mode", mode, nullable=False, server_default="cash"),
        sa.Column(
            "bank_account_id",
            sa.Integer(),
            sa.ForeignKey("bank_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("extra_cost_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column(
            "journal_entry_id",
            sa.Integer(),
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
    op.create_unique_constraint("uq_gold_purchases_no", "gold_purchases", ["purchase_no"])
    op.create_index("ix_gold_purchases_no", "gold_purchases", ["purchase_no"])
    op.create_index("ix_gold_purchases_supplier_id", "gold_purchases", ["supplier_id"])
    op.create_index("ix_gold_purchases_branch_id", "gold_purchases", ["branch_id"])
    op.create_index("ix_gold_purchases_payment_mode", "gold_purchases", ["payment_mode"])
    op.create_index("ix_gold_purchases_bank_account_id", "gold_purchases", ["bank_account_id"])
    op.create_index("ix_gold_purchases_journal_entry_id", "gold_purchases", ["journal_entry_id"])

    op.create_table(
        "gold_purchase_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "purchase_id",
            sa.Integer(),
            sa.ForeignKey("gold_purchases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(150), nullable=True),
        sa.Column("purity", sa.Integer(), nullable=False),
        sa.Column("weight_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("rate_per_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("currency", currency, nullable=False, server_default="PKR"),
        sa.Column("fx_rate_to_pkr", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column(
            "inventory_item_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Purity is a karat figure. A zero or a 25 here is a typo that would
        # value the whole bar wrong, and the melt pot is keyed on it.
        sa.CheckConstraint("purity BETWEEN 1 AND 24", name="ck_gold_purchase_item_purity"),
    )
    op.create_index("ix_gold_purchase_items_purchase_id", "gold_purchase_items", ["purchase_id"])


def downgrade() -> None:
    op.drop_table("gold_purchase_items")
    op.drop_table("gold_purchases")
    sa.Enum(name="gold_payment_mode").drop(op.get_bind(), checkfirst=True)
