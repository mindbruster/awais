"""Material settlement on jobs + locked gold rate on products.

Supports the phase-1 correctness fixes:

* `manufacturing_jobs.gold_source_inventory_id` / `stone_source_inventory_id` —
  remember where material came from so it can be credited back (D1, D2).
* `manufacturing_jobs.gold_written_off_g` / `stones_written_off_ct` /
  `cancel_reason` — record material not recovered when a job is cancelled,
  instead of letting it vanish from stock (D2).
* `products.gold_rate_at_cost` — lock the rate a piece's metal was capitalised
  at, so later recomputes can't rewrite historical cost (D3).

Backfill: existing products get their implied rate derived from the material
cost already recorded, so nothing is re-priced by this migration.

Revision ID: 0008_material_settlement
Revises: 0007_audit_material
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_material_settlement"
down_revision: Union[str, None] = "0007_audit_material"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "manufacturing_jobs",
        sa.Column("gold_source_inventory_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "manufacturing_jobs",
        sa.Column("stone_source_inventory_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_manufacturing_jobs_gold_source_inventory",
        "manufacturing_jobs",
        "inventory_items",
        ["gold_source_inventory_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_manufacturing_jobs_stone_source_inventory",
        "manufacturing_jobs",
        "inventory_items",
        ["stone_source_inventory_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "manufacturing_jobs",
        sa.Column(
            "gold_written_off_g",
            sa.Numeric(14, 4),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "manufacturing_jobs",
        sa.Column(
            "stones_written_off_ct",
            sa.Numeric(14, 4),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "manufacturing_jobs",
        sa.Column("cancel_reason", sa.Text(), nullable=True),
    )

    op.add_column(
        "products",
        sa.Column("gold_rate_at_cost", sa.Numeric(14, 4), nullable=True),
    )

    # Backfill the locked rate for products that already carry a material cost,
    # by inverting the formula the costing service used:
    #   material_cost = gold_weight × (purity/24) × rate  +  stones
    # Products with no gold weight, no purity or no material cost keep NULL and
    # will lock their rate on the next costing pass.
    op.execute(
        """
        UPDATE products p
        SET gold_rate_at_cost = sub.implied_rate
        FROM (
            SELECT
                p2.id,
                (p2.material_cost - COALESCE(s.stone_value, 0))
                    / NULLIF(p2.gold_weight_g * (p2.gold_purity::numeric / 24), 0)
                    AS implied_rate
            FROM products p2
            LEFT JOIN (
                SELECT product_id, SUM(weight_ct * rate_per_ct * quantity) AS stone_value
                FROM product_stones
                GROUP BY product_id
            ) s ON s.product_id = p2.id
            WHERE p2.material_cost > 0
              AND p2.gold_weight_g > 0
              AND p2.gold_purity IS NOT NULL
        ) sub
        WHERE p.id = sub.id
          AND sub.implied_rate IS NOT NULL
          AND sub.implied_rate > 0
        """
    )


def downgrade() -> None:
    op.drop_column("products", "gold_rate_at_cost")
    op.drop_column("manufacturing_jobs", "cancel_reason")
    op.drop_column("manufacturing_jobs", "stones_written_off_ct")
    op.drop_column("manufacturing_jobs", "gold_written_off_g")
    op.drop_constraint(
        "fk_manufacturing_jobs_stone_source_inventory",
        "manufacturing_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_manufacturing_jobs_gold_source_inventory",
        "manufacturing_jobs",
        type_="foreignkey",
    )
    op.drop_column("manufacturing_jobs", "stone_source_inventory_id")
    op.drop_column("manufacturing_jobs", "gold_source_inventory_id")
