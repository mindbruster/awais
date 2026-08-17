"""The maker's reckoning: ratti of the returned weight, settled in fine grams.

The model declared eight columns and an enum value that the database never
had. Nothing could write them, and `select(JobLeg)` names every mapped column,
so the workshop screens were querying a shape the table could not produce. This
migration makes the schema match what the code has been describing.

**Ratti of received.** The maker is allowed metal out of the weight he returns,
quoted 1 to 24 against a base of 96, and it is *added* to what he is credited
with rather than subtracted from what he owes. Six ratti on 107.560g of 21k
allows 6.7225g of 21k; credited with 114.2825g and converted at 21/24 that is
99.9972g fine against 100g issued, so he is 0.0028g short. It is a third
convention beside the percentage and the per-100-pieces figure, and it does not
convert into either — those two are measured against what went out, this one
against what came back, and until the job is finished nobody knows that number.

**The purity of what came back.** Pure metal goes to a maker and 21k jewellery
returns. Without `gold_received_purity` the receive path had nothing to convert
against and used the *issued* purity, crediting a 21k return as though it were
pure — about a seventh too much. The job then reads as settled while the metal
is still out.

**Fine columns.** The raw allowed/actual/excess trio compares grams to grams,
which only means something while both ends of the job are the same purity. Once
they are not, the reckoning has to happen in fine grams or it is subtracting
apples from oranges. The raw trio stays as what the scale read; these three
carry what actually settled.

All eight are nullable, or defaulted where the model requires a value. Legs
settled before this migration keep NULL in the fine columns and the receive
path falls back to converting the raw ones exactly as it always did — no
settled job moves.

Revision ID: 0027_maker_ratti
Revises: 0026_trade_billing
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_maker_ratti"
down_revision: Union[str, None] = "0026_trade_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS so a re-run is safe. The new label is only added here and
    # never written in this same transaction, which is what Postgres requires
    # of ALTER TYPE ... ADD VALUE.
    op.execute("ALTER TYPE wastage_basis ADD VALUE IF NOT EXISTS 'ratti_of_received'")

    # --- the maker's allowance ---
    op.add_column("job_legs", sa.Column("wastage_ratti", sa.Numeric(6, 3), nullable=True))
    # The base travels on the leg because 96 is a convention rather than a
    # constant, and a shop that quotes against a different one must not have
    # its old legs re-read against today's.
    op.add_column(
        "job_legs",
        sa.Column("wastage_ratti_base", sa.Integer(), nullable=False, server_default="96"),
    )

    # --- what came back, and at what purity ---
    op.add_column("job_legs", sa.Column("gold_received_purity", sa.Integer(), nullable=True))
    op.add_column(
        "job_legs", sa.Column("gold_received_tunch_pct", sa.Numeric(6, 3), nullable=True)
    )

    # --- the settlement that actually counts ---
    for col in ("wastage_allowed_fine_g", "wastage_actual_fine_g", "wastage_excess_fine_g"):
        op.add_column("job_legs", sa.Column(col, sa.Numeric(14, 4), nullable=True))

    # --- metal the shop owes rather than holds ---
    # A maker will make a piece on his own gold and be owed it back on a date
    # the two of them agree. Nothing else in the system recorded a promise to
    # *deliver* metal, and a promise nobody wrote down is one nobody chases.
    op.add_column("job_legs", sa.Column("metal_due_date", sa.Date(), nullable=True))
    op.create_index("ix_job_legs_metal_due_date", "job_legs", ["metal_due_date"])


def downgrade() -> None:
    op.drop_index("ix_job_legs_metal_due_date", table_name="job_legs")
    op.drop_column("job_legs", "metal_due_date")
    for col in ("wastage_excess_fine_g", "wastage_actual_fine_g", "wastage_allowed_fine_g"):
        op.drop_column("job_legs", col)
    op.drop_column("job_legs", "gold_received_tunch_pct")
    op.drop_column("job_legs", "gold_received_purity")
    op.drop_column("job_legs", "wastage_ratti_base")
    op.drop_column("job_legs", "wastage_ratti")
    # The enum label is deliberately left in place. Removing a value from a
    # Postgres enum means rebuilding the type and every column that uses it,
    # and any leg already settled under this basis would have nothing to be
    # rewritten to. An unused label costs nothing; a lost settlement does.
