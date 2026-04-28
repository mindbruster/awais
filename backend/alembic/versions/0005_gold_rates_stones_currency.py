"""gold rates, stones master, product-stone breakdown, multi-currency on invoices

Revision ID: 0005_gold_rates_stones
Revises: 0004_indexes
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_gold_rates_stones"
down_revision: Union[str, None] = "0004_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Currency enum is shared across gold_rates, stones, invoices. The first
    # `create_table` that references it (gold_rates) auto-creates the type;
    # later usages declare `create_type=False` so the type isn't re-created.
    currency_first = sa.Enum("PKR", "USD", name="currency")
    currency_ref = sa.Enum("PKR", "USD", name="currency", create_type=False)

    op.create_table(
        "gold_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("currency", currency_first, nullable=False),
        sa.Column("rate_per_g", sa.Numeric(14, 4), nullable=False),
        sa.Column("purity", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_gold_rates_rate_date", "gold_rates", ["rate_date"])
    op.create_index("ix_gold_rates_currency", "gold_rates", ["currency"])

    op.create_table(
        "stones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("diamond", "ruby", "emerald", "sapphire", "pearl", "other", name="stone_kind"),
            nullable=False,
        ),
        sa.Column("cut", sa.String(length=40), nullable=True),
        sa.Column("color", sa.String(length=40), nullable=True),
        sa.Column("clarity", sa.String(length=40), nullable=True),
        sa.Column("default_rate_per_ct", sa.Numeric(14, 4), nullable=True),
        sa.Column("currency", currency_ref, nullable=False, server_default="PKR"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stones_name", "stones", ["name"])
    op.create_index("ix_stones_kind", "stones", ["kind"])

    op.create_table(
        "product_stones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("stone_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("weight_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("rate_per_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stone_id"], ["stones.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_product_stones_product_id", "product_stones", ["product_id"])
    op.create_index("ix_product_stones_stone_id", "product_stones", ["stone_id"])

    # Add currency to invoices (default PKR for backfill)
    op.add_column(
        "invoices",
        sa.Column("currency", currency_ref, nullable=False, server_default="PKR"),
    )
    op.create_index("ix_invoices_currency", "invoices", ["currency"])


def downgrade() -> None:
    op.drop_index("ix_invoices_currency", table_name="invoices")
    op.drop_column("invoices", "currency")

    op.drop_index("ix_product_stones_stone_id", table_name="product_stones")
    op.drop_index("ix_product_stones_product_id", table_name="product_stones")
    op.drop_table("product_stones")

    op.drop_index("ix_stones_kind", table_name="stones")
    op.drop_index("ix_stones_name", table_name="stones")
    op.drop_table("stones")
    sa.Enum(name="stone_kind").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_gold_rates_currency", table_name="gold_rates")
    op.drop_index("ix_gold_rates_rate_date", table_name="gold_rates")
    op.drop_table("gold_rates")

    sa.Enum(name="currency").drop(op.get_bind(), checkfirst=True)
