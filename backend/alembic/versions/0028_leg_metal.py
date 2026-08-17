"""A leg says which metal it is working.

`JobLeg.metal` was declared on the model and never given to the database, so
every query that named the column — which is every query that loads a leg,
since SQLAlchemy selects all mapped columns — failed with `column
job_legs.metal does not exist`. Minting a design, listing the workshop, opening
a trace: all 500. The routing engine was unreachable in practice.

The column exists because the shop gives silver to the same three workers it
gives gold to, and everything between issue and receive — the wastage
reckoning, the worker's running balance, the stock — works identically for
both. What must never happen is a gram of one settling a gram of the other, and
that requires the leg to say which it is.

Purity is deliberately not part of this enum. Gold is quoted in karat and
silver in fineness, which look like different scales but both reduce to a
percentage of pure: 21k is 87.5, 999 silver is 99.9. The tunch column carries
that for both, so this enum only has to say which metal, never how pure.

Every existing leg is gold — silver could not be recorded before this — so the
backfill is a server default rather than a guess.

Revision ID: 0028_leg_metal
Revises: 0027_maker_ratti
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_leg_metal"
down_revision: Union[str, None] = "0027_maker_ratti"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

metal = postgresql.ENUM("gold", "silver", name="metal", create_type=False)


def upgrade() -> None:
    metal.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "job_legs",
        sa.Column("metal", metal, nullable=False, server_default="gold"),
    )
    op.create_index("ix_job_legs_metal", "job_legs", ["metal"])


def downgrade() -> None:
    op.drop_index("ix_job_legs_metal", table_name="job_legs")
    op.drop_column("job_legs", "metal")
    metal.drop(op.get_bind(), checkfirst=True)
