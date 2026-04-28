"""phase 13 — supporting indexes for common filter/order paths

Revision ID: 0004_indexes
Revises: 0003_phase7_costs
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_indexes"
down_revision: Union[str, None] = "0003_phase7_costs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hot order columns — list views all sort by id desc, but a created_at
    # index supports date-range reports and "most recent" UIs.
    op.create_index("ix_invoices_issued_at", "invoices", ["issued_at"])
    op.create_index("ix_invoices_created_at", "invoices", ["created_at"])
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"])
    op.create_index("ix_manufacturing_jobs_created_at", "manufacturing_jobs", ["created_at"])

    # Reports that group by status/type benefit from these (sales/profit reports).
    op.create_index(
        "ix_invoices_status_issued_at",
        "invoices",
        ["status", "issued_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_status_issued_at", table_name="invoices")
    op.drop_index("ix_manufacturing_jobs_created_at", table_name="manufacturing_jobs")
    op.drop_index("ix_stock_movements_created_at", table_name="stock_movements")
    op.drop_index("ix_invoices_created_at", table_name="invoices")
    op.drop_index("ix_invoices_issued_at", table_name="invoices")
