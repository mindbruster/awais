"""Sale wastage, payments, and the two buying channels.

Completes the money side of the shop.

SALES. Wastage charged to the customer — the shop bills for more gold than the
piece contains — quoted as a percentage or as flat grams. It is revenue and one
of the three margin levers alongside the rate spread and making charges, so it
is stored as its own figure rather than folded into the weight. Plus the paper
bill-book number the shop reconciles against, and an explicit round-off: a
round-off that silently adjusts the total is an untracked discount the margin
report can never see.

PAYMENTS. There were none. `mark-paid` flipped a status flag, so nothing
recorded how much was taken, when, by what method, or what was still
outstanding — a shop cannot chase a balance it never wrote down. Payments
carry cash, bank, advances, and gold taken in exchange, in both directions:
when a customer's old jewellery is worth more than the piece they are buying,
the change goes back over the counter.

PURCHASING. Old gold bought back over the counter at a spread below the day's
rate, and stones bought from suppliers as graded lots. Suppliers are kept apart
from workers: a supplier is owed money for goods, a worker is owed labour and
may be holding the shop's metal.

Revision ID: 0012_sales_payments_purchasing
Revises: 0011_ratti_pieces_wastage
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_sales_purchasing"
down_revision: Union[str, None] = "0011_ratti_pieces_wastage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    # ---------------- sales ----------------
    op.add_column("invoices", sa.Column("bill_book_no", sa.String(50), nullable=True))
    op.add_column(
        "invoices", sa.Column("round_off", sa.Numeric(14, 2), nullable=False, server_default="0")
    )
    op.create_index("ix_invoices_bill_book_no", "invoices", ["bill_book_no"])

    op.add_column(
        "invoice_items",
        sa.Column("sale_wastage_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),
    )
    op.add_column(
        "invoice_items",
        sa.Column("sale_wastage_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
    )

    # Costing figures the stock form fills in when a design becomes a product.
    op.add_column("products", sa.Column("gross_weight_g", sa.Numeric(12, 4), nullable=True))
    op.add_column(
        "products", sa.Column("other_charges", sa.Numeric(14, 2), nullable=False, server_default="0")
    )
    op.add_column("products", sa.Column("stocked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("design_id", sa.Integer(), nullable=True))
    op.create_index("ix_products_design_id", "products", ["design_id"])
    op.create_foreign_key(
        "fk_products_design", "products", "designs", ["design_id"], ["id"], ondelete="SET NULL"
    )

    # ---------------- payments ----------------
    payment_method = postgresql.ENUM(
        "cash", "bank", "gold_exchange", "advance", name="payment_method", create_type=False
    )
    payment_method.create(op.get_bind(), checkfirst=True)
    payment_direction = postgresql.ENUM(
        "received", "paid", name="payment_direction", create_type=False
    )
    payment_direction.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_no", sa.String(50), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("method", payment_method, nullable=False),
        sa.Column("direction", payment_direction, nullable=False, server_default="received"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("gold_weight_g", sa.Numeric(14, 4), nullable=True),
        sa.Column("gold_purity", sa.Integer(), nullable=True),
        sa.Column("gold_rate_per_g", sa.Numeric(14, 4), nullable=True),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_unique_constraint("uq_payments_payment_no", "payments", ["payment_no"])
    op.create_index("ix_payments_payment_no", "payments", ["payment_no"])
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])
    op.create_index("ix_payments_customer_id", "payments", ["customer_id"])
    op.create_index("ix_payments_method", "payments", ["method"])
    op.create_index("ix_payments_direction", "payments", ["direction"])
    op.create_index("ix_payments_bank_account_id", "payments", ["bank_account_id"])
    op.create_index("ix_payments_journal_entry_id", "payments", ["journal_entry_id"])

    # ---------------- suppliers ----------------
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("opening_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        *_ts(),
    )
    op.create_unique_constraint("uq_suppliers_name", "suppliers", ["name"])
    op.create_index("ix_suppliers_name", "suppliers", ["name"])
    op.create_index("ix_suppliers_is_active", "suppliers", ["is_active"])

    # ---------------- old gold purchases ----------------
    gold_kind = postgresql.ENUM("pure", "used", name="gold_kind", create_type=False)
    gold_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "old_gold_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_no", sa.String(50), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("walk_in_name", sa.String(150), nullable=True),
        sa.Column("kind", gold_kind, nullable=False, server_default="used"),
        sa.Column("weight_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("purity", sa.Integer(), nullable=True),
        sa.Column("rate_per_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("inventory_item_id", sa.Integer(), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_unique_constraint(
        "uq_old_gold_purchases_purchase_no", "old_gold_purchases", ["purchase_no"]
    )
    op.create_index("ix_old_gold_purchases_purchase_no", "old_gold_purchases", ["purchase_no"])
    op.create_index("ix_old_gold_purchases_customer_id", "old_gold_purchases", ["customer_id"])
    op.create_index("ix_old_gold_purchases_kind", "old_gold_purchases", ["kind"])
    op.create_index("ix_old_gold_purchases_journal", "old_gold_purchases", ["journal_entry_id"])

    # ---------------- stone purchases ----------------
    op.create_table(
        "stone_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_no", sa.String(50), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("extra_cost_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_unique_constraint(
        "uq_stone_purchases_purchase_no", "stone_purchases", ["purchase_no"]
    )
    op.create_index("ix_stone_purchases_purchase_no", "stone_purchases", ["purchase_no"])
    op.create_index("ix_stone_purchases_supplier_id", "stone_purchases", ["supplier_id"])
    op.create_index("ix_stone_purchases_journal", "stone_purchases", ["journal_entry_id"])

    op.create_table(
        "stone_purchase_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_id", sa.Integer(), nullable=False),
        sa.Column("stone_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("rate_per_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("quality", sa.String(60), nullable=True),
        sa.Column("cut", sa.String(40), nullable=True),
        sa.Column("color", sa.String(40), nullable=True),
        sa.Column("clarity", sa.String(40), nullable=True),
        sa.Column("inventory_item_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_ts(),
        sa.ForeignKeyConstraint(["purchase_id"], ["stone_purchases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stone_id"], ["stones.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_stone_purchase_items_purchase_id", "stone_purchase_items", ["purchase_id"])
    op.create_index("ix_stone_purchase_items_stone_id", "stone_purchase_items", ["stone_id"])


def downgrade() -> None:
    op.drop_table("stone_purchase_items")
    op.drop_table("stone_purchases")
    op.drop_table("old_gold_purchases")
    sa.Enum(name="gold_kind").drop(op.get_bind(), checkfirst=True)
    op.drop_table("suppliers")
    op.drop_table("payments")
    for name in ("payment_direction", "payment_method"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)

    op.drop_constraint("fk_products_design", "products", type_="foreignkey")
    op.drop_index("ix_products_design_id", table_name="products")
    for col in ("design_id", "stocked_at", "other_charges", "gross_weight_g"):
        op.drop_column("products", col)
    op.drop_column("invoice_items", "sale_wastage_g")
    op.drop_column("invoice_items", "sale_wastage_pct")
    op.drop_index("ix_invoices_bill_book_no", table_name="invoices")
    op.drop_column("invoices", "round_off")
    op.drop_column("invoices", "bill_book_no")
