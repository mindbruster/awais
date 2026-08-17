"""The setter's reckoning: gross weight in, net metal out, and where each carat went.

A stone setter is handed a piece and a parcel of stones and hands back one
object. The system had no way to read that object.

**Gross and net.** What the scale says when the piece comes back includes the
stones set into it. The reckoning compared that figure directly against the
metal issued, so a piece carrying 30ct looked six grams heavier than it was and
the setter appeared to have *gained* metal on a job he had lost some on. The
gross is now recorded as the counter saw it and the metal is what remains once
the set stones are taken back out at five carats to the gram:

    out   100.000 g of 21k + 30.00 ct (6.000 g)  = 106.000 g
    back  gross 102.000 g, 29.50 ct set (5.900 g)
    net metal   102.000 - 5.900                  =  96.100 g
    short       100.000 - 96.100                 =   3.900 g
    allowed     0.400 / 100 x 350 stones         =   1.400 g
    receivable                                       2.500 g of 21k

**Where each carat went.** Issued carats now have to account for themselves:
set into the piece, handed back loose, broken, or owed by the setter. The four
add back to what went out. Before this the only question asked was how many
came back, so a stone that was neither returned nor set simply vanished from
the record — the shop could not tell a chipped diamond from a stolen one, and
neither produced a claim on anybody.

Broken stones are stock, not a loss. They are still the shop's property and
still sell, so they move to their own inventory category at cost rather than
being expensed; nothing is lost until they are disposed of. They are kept apart
from whole stones because they cannot do the job whole ones were bought for,
and counting them in a stock figure promises material that cannot be issued.

**The debt.** Carats the setter cannot produce become a claim on him, in
carats, on new account 1170. Grams and carats cannot share a balance and the
two settle separately — he can be short metal and short stones at once — so
1160 could not carry it. `STONE` joins the commodity enum for the same reason:
the ledger balances on rupee value, not on quantity, so a carat claim can sit
beside a gram claim in one entry without either pretending to be the other.

Stone *inventory* stays out of the ledger, exactly as `post_stocking`
describes. Nothing here debits or credits 1140. The only stone figure that
reaches the books is the one that is a debt rather than a shelf.

**The rate.** Lost stones are charged at what they would have sold for, not
what the parcel cost, so `stones.selling_rate_per_ct` is added and snapshotted
onto the leg line when the charge is raised. Charging cost would mean a setter
who loses a stone pays the shop's purchase price and the shop eats its margin.

Every column is defaulted, so legs already settled read exactly as they did:
their gross equals their net, nothing was set, nothing was broken, nothing is
owed.

Revision ID: 0029_stone_setting
Revises: 0028_leg_metal
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_stone_setting"
down_revision: Union[str, None] = "0028_leg_metal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_ACCOUNTS = [
    ("1170", "Stones with Workers", "asset", "1100"),
]


def upgrade() -> None:
    # --- the leg: what the scale read, and where the carats went ---
    op.add_column(
        "job_legs",
        sa.Column(
            "gold_received_gross_g", sa.Numeric(14, 4), nullable=False, server_default="0"
        ),
    )
    for col in ("stones_set_ct", "stones_broken_ct", "stones_owed_ct"):
        op.add_column(
            "job_legs", sa.Column(col, sa.Numeric(14, 4), nullable=False, server_default="0")
        )
    # A settled leg's gross is its net: it carried no stones, or the reckoning
    # was done before stones were part of it. Leaving these at zero would make
    # every historic receipt look like a piece that weighed nothing.
    op.execute("UPDATE job_legs SET gold_received_gross_g = gold_received_g")

    # --- the stone lines: set, broken, and what the shortfall is charged at ---
    for col in ("quantity_set", "quantity_broken"):
        op.add_column(
            "leg_stones", sa.Column(col, sa.Integer(), nullable=False, server_default="0")
        )
    for col in ("weight_set_ct", "weight_broken_ct", "owed_rate_per_ct"):
        op.add_column(
            "leg_stones", sa.Column(col, sa.Numeric(14, 4), nullable=False, server_default="0")
        )

    # Restate settled legs in the new vocabulary rather than leaving them at
    # zero and teaching every reader a fallback.
    #
    # The old model asked one question — how many came back — and everything
    # else was taken to be in the piece. So for a leg already received, "issued
    # less returned" *is* what it meant by set, exactly. Writing that down here
    # means `weight_set_ct` is the single figure the costing, the trace and the
    # stock report all read, with no branch on when the row was written.
    #
    # Restricted to received legs on purpose. A leg still out with a worker has
    # returned nothing yet, and treating its whole issue as set would tell the
    # costing that stones are already in a piece nobody has seen.
    op.execute(
        """
        UPDATE leg_stones ls
        SET weight_set_ct = GREATEST(ls.weight_issued_ct - ls.weight_returned_ct, 0),
            quantity_set  = GREATEST(ls.quantity_issued - ls.quantity_returned, 0)
        FROM job_legs jl
        WHERE jl.id = ls.leg_id AND jl.status = 'received'
        """
    )
    op.execute(
        """
        UPDATE job_legs jl
        SET stones_set_ct = COALESCE(
            (SELECT SUM(ls.weight_set_ct) FROM leg_stones ls WHERE ls.leg_id = jl.id), 0
        )
        WHERE jl.status = 'received'
        """
    )

    # --- the selling rate on the stone master ---
    op.add_column("stones", sa.Column("selling_rate_per_ct", sa.Numeric(14, 4), nullable=True))

    # --- somewhere for a carat debt to sit ---
    op.execute("ALTER TYPE commodity ADD VALUE IF NOT EXISTS 'STONE'")
    op.execute("ALTER TYPE inventory_type ADD VALUE IF NOT EXISTS 'broken_stone'")
    for code, name, type_, parent_code in NEW_ACCOUNTS:
        op.execute(
            sa.text(
                """
                INSERT INTO accounts
                    (code, name, type, parent_id, is_system, is_postable, is_active)
                VALUES (
                    :code, :name, CAST(:type AS account_type),
                    (SELECT id FROM accounts WHERE code = :parent_code),
                    TRUE, TRUE, TRUE
                )
                ON CONFLICT (code) DO NOTHING
                """
            ).bindparams(code=code, name=name, type=type_, parent_code=parent_code)
        )


def downgrade() -> None:
    # An account that has been posted to is not removed. Dropping it would
    # orphan the lines that reference it and take a real claim on a real worker
    # off the books with them.
    op.execute(
        """
        DELETE FROM accounts
        WHERE code = '1170'
          AND NOT EXISTS (SELECT 1 FROM journal_lines WHERE account_id = accounts.id)
        """
    )
    op.drop_column("stones", "selling_rate_per_ct")
    for col in ("owed_rate_per_ct", "weight_broken_ct", "weight_set_ct",
                "quantity_broken", "quantity_set"):
        op.drop_column("leg_stones", col)
    for col in ("stones_owed_ct", "stones_broken_ct", "stones_set_ct",
                "gold_received_gross_g"):
        op.drop_column("job_legs", col)
    # Enum labels are left in place. Removing one means rebuilding the type and
    # every column using it, and any row already written with the label would
    # have nothing to be rewritten to.
