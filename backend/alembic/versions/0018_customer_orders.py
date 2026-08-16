"""Give a promise to a customer somewhere to live.

A customer ordering a piece, or handing one over the counter to be repaired,
had nowhere to be recorded. Both were being held in someone's head or on a slip
of paper, while the workshop engine that would actually track the work — the
design and its legs — could only be started from the shop's own side.

This adds the front door. An order is a promise, not a ledger document: it
moves no metal and earns no money, so it posts nothing. The advance is an
ordinary payment against the customer and the delivery is an ordinary invoice;
both are linked from the order rather than reimplemented, which keeps one code
path to the books.

`order_events` is the customer-facing history — what a counter hand reads out
over the phone. The audit log already answers "who changed this row"; it does
not answer "what do I tell the customer".

Revision ID: 0018_customer_orders
Revises: 0017_transfer_movements
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_customer_orders"
down_revision: Union[str, None] = "0017_transfer_movements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES = ("draft", "confirmed", "in_progress", "ready", "delivered", "cancelled")


def upgrade() -> None:
    # Created explicitly, then referenced with create_type=False below —
    # `order_status` appears on three columns across two tables, and a bare
    # sa.Enum would emit CREATE TYPE once per column.
    sa.Enum("custom", "repair", name="order_kind").create(op.get_bind(), checkfirst=True)
    sa.Enum(*_STATUSES, name="order_status").create(op.get_bind(), checkfirst=True)
    order_kind = postgresql.ENUM("custom", "repair", name="order_kind", create_type=False)
    order_status = postgresql.ENUM(*_STATUSES, name="order_status", create_type=False)

    op.create_table(
        "customer_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_no", sa.String(40), nullable=False),
        sa.Column("kind", order_kind, nullable=False),
        sa.Column("status", order_status, nullable=False, server_default="draft"),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.Integer(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("promised_date", sa.Date()),
        sa.Column("estimate_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("intake_weight_g", sa.Numeric(14, 4)),
        sa.Column("intake_purity", sa.Integer()),
        sa.Column("intake_notes", sa.Text()),
        sa.Column("image_url", sa.String(500)),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("design_id", sa.Integer(), sa.ForeignKey("designs.id", ondelete="SET NULL")),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="SET NULL")),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_reason", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_customer_orders_order_no", "customer_orders", ["order_no"], unique=True)
    for col in ("kind", "status", "customer_id", "branch_id", "promised_date", "product_id",
                "design_id", "invoice_id"):
        op.create_index(f"ix_customer_orders_{col}", "customer_orders", [col])

    op.create_table(
        "order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("customer_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", order_status),
        sa.Column("to_status", order_status),
        sa.Column("note", sa.Text()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_order_events_order_id", "order_events", ["order_id"])
    op.create_index("ix_order_events_user_id", "order_events", ["user_id"])


def downgrade() -> None:
    op.drop_table("order_events")
    op.drop_table("customer_orders")
    sa.Enum(name="order_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="order_kind").drop(op.get_bind(), checkfirst=True)
