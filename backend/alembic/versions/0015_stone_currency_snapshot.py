"""Snapshot a currency and FX rate alongside every stone rate.

Three tables record a stone rate — `product_stones`, `leg_stones` and
`stone_purchase_items` — and all three stored the number without the currency
it was quoted in. Two consequences, both silent:

* A stone priced in dollars contributed its raw figure to a rupee cost.
  `material_cost` on a piece set with USD stones was understated by the whole
  exchange rate, and so was every profit figure derived from it.
* The rate was snapshotted but the currency was not, so it was read back off
  the stone master. Editing that master's currency retroactively changed what
  every historical row meant — the definition of a figure that cannot be
  trusted.

A rate without its currency is not a price, it is a number. Both now travel
together, with the conversion locked at the moment the row is written, exactly
as the gold rate and the invoice FX rate already are.

Existing rows are backfilled as PKR at 1:1, which is what they were: nothing in
the system could have priced a stone in anything else, because nothing could
convert it.

Revision ID: 0015_stone_currency
Revises: 0014_exchange_rates
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_stone_currency"
down_revision: Union[str, None] = "0014_exchange_rates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("product_stones", "leg_stones", "stone_purchase_items")


def upgrade() -> None:
    currency = postgresql.ENUM("PKR", "USD", name="currency", create_type=False)
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("currency", currency, nullable=False, server_default="PKR"),
        )
        op.add_column(
            table,
            # Rupees per unit of `currency` at the moment this row was written.
            # 1 for PKR. Held per row rather than looked up later so a piece
            # costed in March keeps March's conversion.
            sa.Column(
                "fx_rate_to_pkr",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="1",
            ),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "fx_rate_to_pkr")
        op.drop_column(table, "currency")
