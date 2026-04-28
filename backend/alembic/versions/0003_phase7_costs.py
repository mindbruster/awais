"""phase 7: cost columns on manufacturing_jobs and total_cost on products

Revision ID: 0003_phase7_costs
Revises: 0002_phase3_to_6
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase7_costs"
down_revision: Union[str, None] = "0002_phase3_to_6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "manufacturing_jobs",
        sa.Column("karigar_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "manufacturing_jobs",
        sa.Column("stone_fixing_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "manufacturing_jobs",
        sa.Column("polish_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "manufacturing_jobs",
        sa.Column("other_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "products",
        sa.Column("total_cost", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("products", "total_cost")
    op.drop_column("manufacturing_jobs", "other_cost")
    op.drop_column("manufacturing_jobs", "polish_cost")
    op.drop_column("manufacturing_jobs", "stone_fixing_cost")
    op.drop_column("manufacturing_jobs", "karigar_cost")
