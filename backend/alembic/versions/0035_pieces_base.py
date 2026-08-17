"""A setting wastage figure is quoted per whatever number the deal was struck in.

`0.400 g per 100 stones` is the common way to say it, and the column that holds
it is named for that. The hundred itself was hard-coded into the arithmetic,
which made every other quote unrecordable: a shop that agreed 0.400 g per 250
had to divide it down by hand before typing it, and the figure it actually
shook hands on never appeared anywhere. Per 50, per 250, per 1000 are all real.

So the base travels on the leg, exactly as the ratti base does and for the same
reason — it is a convention, not a constant, and a leg must settle against the
deal that was in force when the metal left the safe rather than against
whatever the department is set to today.

    allowed = per_base / base * pieces

A hundred is the default, so every leg already settled and every department
already configured keeps computing to the same figure it always did. Nothing
moves.

Revision ID: 0035_pieces_base
Revises: 0034_invoice_kind
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_pieces_base"
down_revision: Union[str, None] = "0034_invoice_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_legs",
        sa.Column("wastage_pieces_base", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "departments",
        sa.Column(
            "default_wastage_pieces_base", sa.Integer(), nullable=False, server_default="100"
        ),
    )
    # A base of zero would divide the allowance by nothing. Guarded in the
    # database as well as the schema, because this is the sort of figure a bulk
    # import sets without going through the API.
    op.create_check_constraint(
        "ck_job_legs_wastage_pieces_base_positive", "job_legs", "wastage_pieces_base > 0"
    )
    op.create_check_constraint(
        "ck_departments_wastage_pieces_base_positive",
        "departments",
        "default_wastage_pieces_base > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_departments_wastage_pieces_base_positive", "departments", type_="check"
    )
    op.drop_constraint("ck_job_legs_wastage_pieces_base_positive", "job_legs", type_="check")
    op.drop_column("departments", "default_wastage_pieces_base")
    op.drop_column("job_legs", "wastage_pieces_base")
