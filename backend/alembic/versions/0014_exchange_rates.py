"""Exchange rates, so the shop can actually deal in dollars.

The invoice, gold-rate, stone and bank-account tables have carried a currency
since the beginning, and the ledger has had a USD commodity since it was built.
What was missing was the one thing that makes any of it usable: a rate. Without
it a dollar invoice could be priced and then refused at posting time, which is
the worst of both worlds — the shop can raise a bill it cannot put in its books.

PKR stays the book currency. A shop keeps one set of books, and every balance
and report has to add up in a single unit. Dealing in dollars changes what has
to be converted and at which rate, not what the books are kept in.

No PKR row is ever stored: the base converts to itself at exactly 1, and a row
saying otherwise would let someone revalue the entire book by typing in a box.

Revision ID: 0014_exchange_rates
Revises: 0013_cogs_account
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_exchange_rates"
down_revision: Union[str, None] = "0013_cogs_account"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "currency",
            postgresql.ENUM("PKR", "USD", name="currency", create_type=False),
            nullable=False,
        ),
        sa.Column("rate_date", sa.Date(), nullable=False),
        # Rupees per one unit. Six decimals because a rate is quoted to more
        # precision than money is held in, and rounding it at entry would move
        # every converted figure derived from it.
        sa.Column("pkr_per_unit", sa.Numeric(18, 6), nullable=False),
        sa.Column("notes", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_exchange_rates_currency", "exchange_rates", ["currency"])
    op.create_index("ix_exchange_rates_rate_date", "exchange_rates", ["rate_date"])
    # The resolver asks for "the latest rate for this currency on or before a
    # date" on every posting that touches foreign money.
    op.create_index(
        "ix_exchange_rates_lookup", "exchange_rates", ["currency", "rate_date"]
    )

    # Invoices already carry a currency; what they lacked was the rate they were
    # converted at. Snapshotted per invoice so a dollar bill raised in March
    # stays valued at March's rate — re-translating it as the rupee moves would
    # rewrite last quarter's profit every time a report was opened.
    op.add_column("invoices", sa.Column("fx_rate_to_pkr", sa.Numeric(18, 6), nullable=True))
    op.add_column("payments", sa.Column("currency", postgresql.ENUM("PKR", "USD", name="currency", create_type=False), nullable=False, server_default="PKR"))
    op.add_column("payments", sa.Column("fx_rate_to_pkr", sa.Numeric(18, 6), nullable=True))
    op.create_index("ix_payments_currency", "payments", ["currency"])


def downgrade() -> None:
    op.drop_index("ix_payments_currency", table_name="payments")
    op.drop_column("payments", "fx_rate_to_pkr")
    op.drop_column("payments", "currency")
    op.drop_column("invoices", "fx_rate_to_pkr")
    op.drop_table("exchange_rates")
