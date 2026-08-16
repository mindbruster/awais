"""The maker's leg: what came back, what he keeps, and whose metal it was.

Four things the shop does on every job that a leg had no room for.

**What came back is not what went out.** The shop issues pure 24k and the maker
returns 21k jewellery. A leg recorded one purity and used it for both ends, so
the returned weight was valued as though it were pure — crediting a 21k piece
at 24k overstates his delivery by about fourteen percent, and the shop would
read a job as square while the metal was still short. `gold_received_purity`
and `gold_received_tunch_pct` carry the other end of the job. Both are
nullable and read as "the same metal came back" when empty, so every leg
already settled computes exactly as it did.

**The maker's wastage is quoted in ratti, and measured on the wrong end.** Six
ratti of 96 on the 107.560g he hands back allows 6.7225g, added to what he is
credited with. It is not convertible into the percentage the goldsmith works on
or the per-100-pieces the setter works on, because it reckons against the
weight he *returns* rather than the weight he was issued — a number nobody
knows until the job is finished. So it is a third value on `wastage_basis`,
chosen per job rather than defaulted onto a department: the shop agrees wastage
and the per-gram rate as independent switches, and the deal on this piece is
not the deal on the next one.

**Grams stopped being comparable.** With 24k out and 21k back, `issued minus
received` is subtracting different assets: the maker's job reads as coming back
*heavier* while it is in fact square. The three wastage figures are therefore
written again in fine grams, which is where the liability is now settled. The
raw columns stay as what the scale read, because that is what a worker argues
from. Nullable and never backfilled: a leg without them falls back to the old
conversion and reproduces its original entry exactly.

**The metal is not always the shop's.** A maker will make a piece on his own
gold and be owed metal back on a date the two of them agree. `metal_due_date`
records that promise, because one nobody wrote down is one nobody chases.

`metal` rides along on every leg — gold unless stated — so the silver work
that follows does not have to migrate every leg a second time. Purity is not in
it: karat and fineness both reduce to `tunch_pct`, so the enum only has to say
which metal, never how pure.

Reversible in full, except that Postgres cannot drop an enum label — the
downgrade moves any leg still settling in ratti back to the percentage basis
and leaves the unused label in the type, which is harmless.

Revision ID: 0027_maker_leg
Revises: 0026_trade_billing
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_maker_leg"
down_revision: Union[str, None] = "0026_trade_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS so a re-run is safe. ALTER TYPE ... ADD VALUE is permitted
    # inside a transaction from Postgres 12, well below the 16 this targets —
    # but the new label cannot be *compared or cast* in the same transaction
    # that adds it. Nothing here does: the Maker default at the foot of this
    # migration is written to `departments.default_wastage_basis`, which is a
    # 20-character text column rather than the enum, so it never touches the
    # new label as a value of the type.
    op.execute("ALTER TYPE wastage_basis ADD VALUE IF NOT EXISTS 'ratti_of_received'")

    metal = postgresql.ENUM("gold", "silver", name="metal", create_type=False)
    metal.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "job_legs",
        sa.Column("metal", metal, nullable=False, server_default="gold"),
    )
    op.create_index("ix_job_legs_metal", "job_legs", ["metal"])

    # --- what came back ---
    # The issue side already has its tunch column from 0025; only the receive
    # side was missing, which is precisely the half that was being assumed.
    op.add_column("job_legs", sa.Column("gold_received_purity", sa.Integer()))
    op.add_column("job_legs", sa.Column("gold_received_tunch_pct", sa.Numeric(6, 3)))

    # --- the maker's allowance ---
    op.add_column("job_legs", sa.Column("wastage_ratti", sa.Numeric(6, 3)))
    op.add_column(
        "job_legs",
        # 96 is customary but not universal, so it travels on the leg rather
        # than being assumed by the settlement code — the same discipline as
        # `invoice_items.ratti_base`.
        sa.Column("wastage_ratti_base", sa.Integer(), nullable=False, server_default="96"),
    )

    # --- the same reckoning, in fine grams ---
    op.add_column("job_legs", sa.Column("wastage_allowed_fine_g", sa.Numeric(14, 4)))
    op.add_column("job_legs", sa.Column("wastage_actual_fine_g", sa.Numeric(14, 4)))
    op.add_column("job_legs", sa.Column("wastage_excess_fine_g", sa.Numeric(14, 4)))

    # --- metal the shop owes back ---
    op.add_column(
        "job_legs",
        sa.Column("metal_on_credit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("job_legs", sa.Column("metal_due_date", sa.Date()))
    op.create_index("ix_job_legs_metal_due_date", "job_legs", ["metal_due_date"])

    # No department default is moved onto the new basis, deliberately.
    #
    # The obvious thing to do here is switch Maker to ratti, since that is the
    # convention he works to. But the shop was explicit that wastage and the
    # per-gram rate are independent switches decided per job — either, both, or
    # neither — and a department default is not a per-job decision. Making it
    # one would force a ratti figure onto every leg going to the maker,
    # including the jobs where no wastage was agreed at all, and the counter
    # would have to type a nought to say what it already meant.
    #
    # The default stays editable data on the departments screen. A shop that
    # settles every maker job in ratti can set it there in one click, and that
    # is its decision to make rather than this migration's.


def downgrade() -> None:
    # Any leg still filed under the label has to come off it before the column
    # goes, or the enum would be left with rows nothing can read. The percentage
    # basis is the safe landing: it is what every worker's stored rate is
    # already expressed in.
    op.execute(
        "UPDATE job_legs SET wastage_basis = 'percent_of_issued' "
        "WHERE wastage_basis = 'ratti_of_received'"
    )

    op.drop_index("ix_job_legs_metal_due_date", table_name="job_legs")
    op.drop_column("job_legs", "metal_due_date")
    op.drop_column("job_legs", "metal_on_credit")
    op.drop_column("job_legs", "wastage_excess_fine_g")
    op.drop_column("job_legs", "wastage_actual_fine_g")
    op.drop_column("job_legs", "wastage_allowed_fine_g")
    op.drop_column("job_legs", "wastage_ratti_base")
    op.drop_column("job_legs", "wastage_ratti")
    op.drop_column("job_legs", "gold_received_tunch_pct")
    op.drop_column("job_legs", "gold_received_purity")
    op.drop_index("ix_job_legs_metal", table_name="job_legs")
    op.drop_column("job_legs", "metal")
    sa.Enum(name="metal").drop(op.get_bind(), checkfirst=True)
    # Postgres offers no DROP VALUE, so 'ratti_of_received' stays in the type.
    # Harmless once nothing writes it.
