"""A bullion bill has to be able to say which metal it bought.

Everything downstream of a silver purchase already existed: `raw_silver` as its
own stock category, 1135 Silver in Hand and 1136 Silver with Workers, the
`metal` enum on a job leg, a silver rate, a silver column on the stock page and
in the revaluation. Silver could be issued to a karigar, come back as 925, be
valued, revalued and reported.

It simply could not be *bought*. `gold_purchases` had no metal column, so the
only way silver ever entered the system was an opening balance or a hand-written
journal — and a shop that cannot record the bill it was invoiced against cannot
tell you what its silver cost.

**Metal sits on the bill, not on the lot.** A lot-level column would let one
document debit two different control accounts on two different purity scales,
and the line that decides whether 5kg lands in 1130 or 1135 must not be one a
counter hand can set differently on row three. A dealer invoices one metal.

`purity` on the lot loses its NOT NULL for the same reason. It is a karat
integer, and karat cannot describe silver: 999 is not 24 of anything. Silver
states its fineness in `tunch_pct`, which `fine_grams` already prefers wherever
it is present, so a silver lot carries a real number in the field that means
fineness and NULL in the field that means karat — rather than a placeholder 24
that would read, everywhere it was displayed, as pure gold.

Revision ID: 0038_silver_purch
Revises: 0037_metal_reval
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_silver_purch"
down_revision: Union[str, None] = "0037_metal_reval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Created by 0027 for job legs. Referenced, never redefined — a second
# CREATE TYPE would fail, and `create_type=False` is what says "this already
# exists, just use it".
METAL = postgresql.ENUM("gold", "silver", name="metal", create_type=False)


def upgrade() -> None:
    op.add_column(
        "gold_purchases",
        sa.Column("metal", METAL, nullable=False, server_default="gold"),
    )
    # Every bill already on the books is gold — the column could not have held
    # anything else — so the default backfills them correctly. It stays on the
    # column afterwards: a bill written by an older client that does not know
    # the field yet should be gold, which is what it would have been.
    op.create_index("ix_gold_purchases_metal", "gold_purchases", ["metal"])

    op.alter_column(
        "gold_purchase_items",
        "purity",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Silver lots have no karat to put back, so a blind NOT NULL would fail on
    # exactly the rows this migration was written to allow. They are dropped
    # rather than guessed at: inventing a karat for silver is how silver gets
    # counted as gold, which is the whole thing this avoids.
    op.execute("DELETE FROM gold_purchase_items WHERE purity IS NULL")
    op.execute(
        """
        DELETE FROM gold_purchases
        WHERE metal = 'silver'
        """
    )
    op.alter_column(
        "gold_purchase_items",
        "purity",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_index("ix_gold_purchases_metal", table_name="gold_purchases")
    op.drop_column("gold_purchases", "metal")
