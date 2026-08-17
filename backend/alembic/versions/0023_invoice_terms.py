"""Credit terms on a bill, and the shop's own account number for a customer.

The printed invoice this business issues carries four things the system had no
room for: the customer's account number, the credit terms in days, the date the
money falls due, and the invoice's own number in the shop's series. Three of
them are now storable; the due date is derived from the other two rather than
stored, so correcting the terms corrects the date.

`term_days` defaults to 0 — due on issue, which is a counter sale. Trade
customers take 30 or 60, and a bill that does not say so leaves the shop
chasing a date only one side of the conversation knows.

Revision ID: 0023_invoice_terms
Revises: 0022_letterhead
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_invoice_terms"
down_revision: Union[str, None] = "0022_letterhead"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("term_days", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("customers", sa.Column("account_no", sa.String(30), nullable=True))
    op.create_index("ix_customers_account_no", "customers", ["account_no"])


def downgrade() -> None:
    op.drop_index("ix_customers_account_no", table_name="customers")
    op.drop_column("customers", "account_no")
    op.drop_column("invoices", "term_days")
