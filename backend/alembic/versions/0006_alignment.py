"""alignment: per-line invoice discount

Revision ID: 0006_alignment
Revises: 0005_gold_rates_stones
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_alignment"
down_revision: Union[str, None] = "0005_gold_rates_stones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice_items",
        sa.Column("line_discount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("invoice_items", "line_discount")
