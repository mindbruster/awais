"""Track goods let out on approval.

`ProductStatus.on_approval`, `SaleType.on_approval` and the `approval_out` /
`approval_return_in` stock movements all existed already — but nothing drove
them, so a piece let out on approval was indistinguishable from one sitting in
the case. That is the worst state for a jeweller to be in: the piece is neither
on the shelf nor in anyone's sales figures, and the gap surfaces at stock-take,
months later, with nobody able to say who has it.

No ledger entry. A memo is not a sale: the goods are still the shop's asset,
merely somewhere else. Booking revenue when a memo goes out would record a sale
that may never happen, and reversing it afterwards is how turnover becomes
fiction. When the customer keeps a piece, the ordinary invoice does the
ordinary thing and the line points at it.

Revision ID: 0020_approvals
Revises: 0019_notifications
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_approvals"
down_revision: Union[str, None] = "0019_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS = ("out", "partly_returned", "closed", "cancelled")
_LINE = ("out", "returned", "sold")


def upgrade() -> None:
    sa.Enum(*_STATUS, name="approval_status").create(op.get_bind(), checkfirst=True)
    sa.Enum(*_LINE, name="approval_line_status").create(op.get_bind(), checkfirst=True)
    st = postgresql.ENUM(*_STATUS, name="approval_status", create_type=False)
    line = postgresql.ENUM(*_LINE, name="approval_line_status", create_type=False)

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_no", sa.String(40), nullable=False),
        sa.Column("customer_id", sa.Integer(),
                  sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("branch_id", sa.Integer(),
                  sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", st, nullable=False, server_default="out"),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("due_date", sa.Date()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("issued_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        sa.Column("cancelled_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_approvals_approval_no", "approvals", ["approval_no"], unique=True)
    for col in ("customer_id", "branch_id", "status", "due_date", "issued_by_id"):
        op.create_index(f"ix_approvals_{col}", "approvals", [col])

    op.create_table(
        "approval_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_id", sa.Integer(),
                  sa.ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(),
                  sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", line, nullable=False, server_default="out"),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    for col in ("approval_id", "product_id", "status", "invoice_id"):
        op.create_index(f"ix_approval_items_{col}", "approval_items", [col])

    # One piece cannot be out on two memos at once. Enforced in the database
    # because the check is a read followed by a write, and two counters serving
    # two customers in the same minute would both pass it.
    op.create_index(
        "uq_approval_items_product_out",
        "approval_items",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("status = 'out'"),
    )


def downgrade() -> None:
    op.drop_table("approval_items")
    op.drop_table("approvals")
    sa.Enum(name="approval_line_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="approval_status").drop(op.get_bind(), checkfirst=True)
