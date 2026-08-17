"""Stone costing draws from the parcel it was actually bought in.

Stock is one running figure per grade — "120ct of 12 PTR commercial" — because
that is the question the counter asks. Cost is a different question. Those 120
carats are fifty bought in January at Rs 8,000 and seventy bought in March at
Rs 9,200, and a piece made from the January parcel cost Rs 8,000 a carat
however much dearer stone sits beside it on the shelf.

Until now a leg line took the stone master's standing rate, which is neither
figure and moves whenever somebody edits the master. Averaging the parcels
instead would hide the thing worth seeing: a parcel bought dear disappears into
the mean, every piece afterwards looks equally profitable, and the buying
mistake never surfaces on a report.

So `stone_draws` records which parcel each issue came out of and at what rate,
oldest parcel first. The rate stored is the *landed* one — the line rate,
converted at the exchange rate on that bill, loaded with that bill's freight
and certification percentage. All three are editable and a piece's cost must
not move when one is corrected months later, so all three are baked in here.

`purchase_item_id` is nullable on purpose. A shop's opening stone stock
predates this system and so does every parcel bought before it was installed —
there are real carats on the shelf with no purchase line behind them. Refusing
to issue those would mean the shop cannot use its own stones until years of
history are keyed in, so what the parcels cannot cover is drawn against no
parcel, costed at the master's rate, and recorded as such.

Nothing is backfilled. Legs already settled keep the rate they were costed at;
recomputing them would restate finished pieces against parcels chosen by an
algorithm that did not exist when they were made.

Revision ID: 0032_stone_fifo
Revises: 0031_lots
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_stone_fifo"
down_revision: Union[str, None] = "0031_lots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stone_draws",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("leg_stone_id", sa.Integer(), nullable=False),
        sa.Column("purchase_item_id", sa.Integer(), nullable=True),
        sa.Column("weight_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("rate_per_ct_pkr", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # CASCADE from the leg line: a draw has no meaning without the issue it
        # belongs to, and deleting the leg should not leave parcels showing
        # carats consumed by nothing.
        sa.ForeignKeyConstraint(["leg_stone_id"], ["leg_stones.id"], ondelete="CASCADE"),
        # RESTRICT to the parcel: a purchase line that has been drawn from is
        # part of a finished piece's cost, and deleting it would make that cost
        # unexplainable.
        sa.ForeignKeyConstraint(
            ["purchase_item_id"], ["stone_purchase_items.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_stone_draws_leg_stone_id", "stone_draws", ["leg_stone_id"])
    op.create_index("ix_stone_draws_purchase_item_id", "stone_draws", ["purchase_item_id"])


def downgrade() -> None:
    op.drop_index("ix_stone_draws_purchase_item_id", table_name="stone_draws")
    op.drop_index("ix_stone_draws_leg_stone_id", table_name="stone_draws")
    op.drop_table("stone_draws")
