"""Give a branch a letterhead.

Every printed document was headed "Jewelry ERP", which is the name of the
software, not the name of the shop. A customer's copy of a bill is the one
artefact of this system anybody outside the business ever sees, and it was
announcing the vendor instead of the jeweller.

Three fields, on the branch rather than in global config: a business with two
shops prints two different names, and the invoice already knows which branch
raised it. `letterhead_name` is nullable and falls back to `name`, so nothing
has to be filled in before the next bill can be printed.

Revision ID: 0022_letterhead
Revises: 0021_three_stages
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_letterhead"
down_revision: Union[str, None] = "0021_three_stages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("letterhead_name", sa.String(120), nullable=True))
    op.add_column("branches", sa.Column("tagline", sa.String(160), nullable=True))
    op.add_column("branches", sa.Column("logo_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "logo_url")
    op.drop_column("branches", "tagline")
    op.drop_column("branches", "letterhead_name")
