"""Lots: metal goes out as one weight and comes back as several pieces.

A hundred grams goes to a maker and twelve bangles come back. Until they come
back there is nothing to number individually — no weights, and often not even a
firm count — so the system had a choice between minting twelve empty design
numbers on day one and minting nothing at all. It did the second, which meant a
lot of metal sitting with a maker was identified by nobody's name and a date.

A **lot** is minted when the metal leaves, takes a `LOT-00001` number from its
own sequence, and is what the shop chases while the work is out. When the
pieces arrive the lot *splits*: one design per piece, each weighed
individually, each taking its own `TK-00001` from the item, and each carrying
that number through setting, stock and sale.

Weighed individually rather than the lot weight divided evenly. Twelve bangles
differ by a gram either way, and an average would leave every piece's cost,
price and wastage computed from a weight it never had.

The lot is a Design rather than a table of its own, because everything a lot
does a design already does — it takes legs, holds a worker, posts to the ledger
and appears on the floor. A second model would mean two of each of those,
differing only in what the row is called.

`split` joins the status enum so a divided lot leaves the worklist. The row
stays: it is the dealing with the maker and the ledger entries hang off it, but
it is no longer a thing on the bench.

Every existing design is a single piece, so the backfill is a default: not a
lot, no parent, no allotted weight.

Revision ID: 0031_lots
Revises: 0030_silver
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_lots"
down_revision: Union[str, None] = "0030_silver"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE design_status ADD VALUE IF NOT EXISTS 'split'")

    op.add_column(
        "designs",
        sa.Column("is_lot", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_designs_is_lot", "designs", ["is_lot"])
    op.add_column(
        "designs",
        sa.Column("expected_pieces", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("designs", sa.Column("parent_design_id", sa.Integer(), nullable=True))
    op.create_index("ix_designs_parent_design_id", "designs", ["parent_design_id"])
    # RESTRICT, not CASCADE. Deleting a lot must not silently take twelve
    # finished pieces — and their serials, their invoices and their ledger
    # history — down with it.
    op.create_foreign_key(
        "fk_designs_parent_design_id",
        "designs",
        "designs",
        ["parent_design_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # What the piece weighed when its lot was divided, and at what purity. A
    # piece has no leg until it is issued somewhere, so without these there is
    # nothing on the row saying how heavy it is — and the next department has to
    # be issued a weight.
    op.add_column("designs", sa.Column("piece_weight_g", sa.Numeric(14, 4), nullable=True))
    op.add_column("designs", sa.Column("piece_purity", sa.Integer(), nullable=True))
    op.add_column("designs", sa.Column("piece_tunch_pct", sa.Numeric(6, 3), nullable=True))
    op.create_check_constraint(
        "ck_designs_piece_tunch_pct_range",
        "designs",
        "piece_tunch_pct IS NULL OR (piece_tunch_pct > 0 AND piece_tunch_pct <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_designs_piece_tunch_pct_range", "designs", type_="check")
    op.drop_column("designs", "piece_tunch_pct")
    op.drop_column("designs", "piece_purity")
    op.drop_column("designs", "piece_weight_g")
    op.drop_constraint("fk_designs_parent_design_id", "designs", type_="foreignkey")
    op.drop_index("ix_designs_parent_design_id", table_name="designs")
    op.drop_column("designs", "parent_design_id")
    op.drop_column("designs", "expected_pieces")
    op.drop_index("ix_designs_is_lot", table_name="designs")
    op.drop_column("designs", "is_lot")
    # The `split` label stays. Removing an enum value means rebuilding the type
    # and every column using it, and a lot already divided would have no status
    # to be rewritten to.
