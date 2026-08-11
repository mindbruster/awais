"""Ratti discounts, piece counts, and the per-100-pieces wastage basis.

Three rules from the shop that the model had no room for.

1. Discounts are quoted in *ratti*, not percentages: "6 ratti off" bills
   weight/96 * 90. It is a proportional reduction of billable gold, which is how
   this trade discounts without touching the rate.

2. Setting is agreed per hundred stones, not as a percentage of weight —
   0.400g per 100 over 350 stones allows 1.400g. A setter's loss tracks how many
   stones he handles, so a percentage would under-charge a light piece carrying
   many stones and over-charge a heavy one carrying few. That makes the wastage
   basis a per-leg property, snapshotted like the rate.

3. Setting and lacquering charge by the piece — 5 or 10 rupees a stone, 500 or
   1000 an item — so a leg has to carry how many pieces it covered.

The Setting department is switched to the per-100 basis here; the rest keep the
percentage convention.

Revision ID: 0011_ratti_pieces_wastage
Revises: 0010_ledger_and_routing
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_ratti_pieces_wastage"
down_revision: Union[str, None] = "0010_ledger_and_routing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- ratti discount on sale lines ---
    op.add_column(
        "invoice_items",
        sa.Column("discount_ratti", sa.Numeric(8, 3), nullable=False, server_default="0"),
    )
    op.add_column(
        # 96 is customary but not universal, so it travels with the line rather
        # than being assumed by the pricing code.
        "invoice_items",
        sa.Column("ratti_base", sa.Integer(), nullable=False, server_default="96"),
    )

    # --- piece counts and the wastage basis on legs ---
    wastage_basis = postgresql.ENUM(
        "percent_of_issued", "per_100_pieces", name="wastage_basis", create_type=False
    )
    wastage_basis.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "job_legs", sa.Column("piece_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "job_legs",
        sa.Column(
            "wastage_basis", wastage_basis, nullable=False, server_default="percent_of_issued"
        ),
    )
    op.add_column(
        "job_legs", sa.Column("wastage_per_100_pcs_g", sa.Numeric(14, 4), nullable=True)
    )

    # --- department defaults, so the floor doesn't retype them per job ---
    op.add_column(
        "departments",
        sa.Column(
            "default_wastage_basis",
            sa.String(20),
            nullable=False,
            server_default="percent_of_issued",
        ),
    )
    op.add_column(
        "departments",
        sa.Column("default_wastage_per_100_pcs_g", sa.Numeric(14, 4), nullable=True),
    )
    op.add_column(
        "departments", sa.Column("default_rate_per_piece", sa.Numeric(14, 4), nullable=True)
    )

    # Setting is the stone-consuming stage and the one that works per hundred.
    # 0.400g/100 and 5 rupees a stone are the figures the shop quoted; both are
    # editable from the departments screen.
    op.execute(
        """
        UPDATE departments
        SET default_wastage_basis = 'per_100_pieces',
            default_wastage_per_100_pcs_g = 0.4000,
            default_rate_per_piece = 5.0000
        WHERE code = 'SET'
        """
    )


def downgrade() -> None:
    op.drop_column("departments", "default_rate_per_piece")
    op.drop_column("departments", "default_wastage_per_100_pcs_g")
    op.drop_column("departments", "default_wastage_basis")
    op.drop_column("job_legs", "wastage_per_100_pcs_g")
    op.drop_column("job_legs", "wastage_basis")
    op.drop_column("job_legs", "piece_count")
    sa.Enum(name="wastage_basis").drop(op.get_bind(), checkfirst=True)
    op.drop_column("invoice_items", "ratti_base")
    op.drop_column("invoice_items", "discount_ratti")
