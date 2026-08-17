"""Silver: its own stock, its own rate, its own accounts.

The shop buys pure silver at 999 and gives it to the same three workers it
gives gold to. Everything between issue and receive works identically — the
wastage reckoning, the worker's running balance, the stock — but the two metals
are not interchangeable, and a gram of one must never settle a gram of the
other. `job_legs.metal` said which since 0028; nothing downstream could act on
it, because there was nowhere for silver to be stocked, valued or owed.

**Purity is a different scale.** Gold is quoted in karat out of 24, silver in
fineness out of a thousand. They are not two ways of saying the same thing:
925 cannot be written as a karat at all, and 999 silver left to the karat
fallback would be read as 24 and valued as pure. So silver states its purity in
the `tunch_pct` columns, which already hold a percentage of pure and already
serve both metals, and the karat columns stay gold's alone.

**The rate.** `gold_rates` gains `metal` and `fineness_pct`. The ledger values
metal per gram of *pure*; the shop quotes "999 silver, Rs 340 a gram". For 24k
gold those are the same number, which is why nothing needed the distinction
while the system only knew gold. For silver they differ by a tenth of a
percent — small on a gram, not small on a few kilos — so `fineness_pct` records
what the quote was quoted at and the division happens in one place.

The table keeps its name. Renaming it would rewrite every reference in the
codebase and every saved query the shop has, to say what the new column says.

**The accounts.** 1135 Silver in Hand and 1165 Silver with Workers, mirroring
1130 and 1160. Not sub-balances of the gold accounts: "how much metal is in the
safe" is not a question with an answer when the two differ a hundredfold in
value, and one account holding both reports a number in no unit at all. The
`SILVER` commodity exists for the same reason — one commodity with a metal flag
would let a gold balance quietly include silver every time somebody summed
without remembering to filter.

Every existing rate row is gold, and every existing leg is gold, so the
backfill is a default rather than a guess.

Revision ID: 0030_silver
Revises: 0029_stone_setting
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_silver"
down_revision: Union[str, None] = "0029_stone_setting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

metal = postgresql.ENUM("gold", "silver", name="metal", create_type=False)

NEW_ACCOUNTS = [
    ("1135", "Silver in Hand", "asset", "1100"),
    ("1165", "Silver with Workers", "asset", "1100"),
]


def upgrade() -> None:
    # The type already exists from 0028, where legs learned which metal they
    # work. Guarded anyway so this migration stands on its own.
    metal.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "gold_rates",
        sa.Column("metal", metal, nullable=False, server_default="gold"),
    )
    op.create_index("ix_gold_rates_metal", "gold_rates", ["metal"])
    op.add_column("gold_rates", sa.Column("fineness_pct", sa.Numeric(6, 3), nullable=True))
    # A fineness is a percentage of pure. Zero is not a reading — it is an
    # empty field somebody typed a nought into — and it would divide the rate
    # by nothing, so the floor is exclusive.
    op.create_check_constraint(
        "ck_gold_rates_fineness_pct_range",
        "gold_rates",
        "fineness_pct IS NULL OR (fineness_pct > 0 AND fineness_pct <= 100)",
    )

    op.execute("ALTER TYPE commodity ADD VALUE IF NOT EXISTS 'SILVER'")
    op.execute("ALTER TYPE inventory_type ADD VALUE IF NOT EXISTS 'raw_silver'")

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
    # Accounts that have been posted to stay. Dropping one would orphan its
    # lines and take real silver off the books with them.
    op.execute(
        """
        DELETE FROM accounts
        WHERE code IN ('1135', '1165')
          AND NOT EXISTS (SELECT 1 FROM journal_lines WHERE account_id = accounts.id)
        """
    )
    op.drop_constraint("ck_gold_rates_fineness_pct_range", "gold_rates", type_="check")
    op.drop_column("gold_rates", "fineness_pct")
    op.drop_index("ix_gold_rates_metal", table_name="gold_rates")
    op.drop_column("gold_rates", "metal")
    # Enum labels stay: removing one means rebuilding the type and every column
    # that uses it, and a row already written with the label would have nothing
    # to be rewritten to. The `metal` type itself belongs to 0028.
