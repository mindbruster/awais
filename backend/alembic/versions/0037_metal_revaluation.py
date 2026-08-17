"""Metal held at cost is not metal held at what it is worth.

A jeweller's capital is mostly gold. Between what it cost and what it is worth
sits the whole reason he watches the rate: a shop can trade flat for a month and
be materially richer, or trade well and be poorer, and a balance sheet at
historic cost says neither.

The shop chose to have this **posted** rather than merely reported, and the
consequences are real — the balance sheet shows metal at market, and profit
includes the rate movement. A falling rate books a loss in a month the floor may
have worked well. That is true, and it is the price of the balance sheet being
true.

**4500 Metal Revaluation** is one account swinging both ways rather than a gain
head and a loss head. It is one phenomenon — the market moved — and splitting it
would make a month containing both a rise and a fall read as unrelated income
and expense for what was a single position moving.

Nothing is added to the metal tables. A revaluation posts *money only*: the gram
balance of 1130 is untouched, because no metal moved, and altering it would
corrupt the one figure that can be counted against the safe. What changes is the
rupee value sitting beside those grams — which is exactly the split
`balance(commodity=GOLD)` and `balance_pkr` already make, and the reason this
needs no new columns at all.

Revision ID: 0037_metal_reval
Revises: 0036_sellers_targets
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_metal_reval"
down_revision: Union[str, None] = "0036_sellers_targets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_ACCOUNTS = [
    ("4500", "Metal Revaluation", "income", "4000"),
]


def upgrade() -> None:
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
    # An account that has been posted to stays: removing it would orphan the
    # lines that hold a real movement in the shop's worth.
    op.execute(
        """
        DELETE FROM accounts
        WHERE code = '4500'
          AND NOT EXISTS (SELECT 1 FROM journal_lines WHERE account_id = accounts.id)
        """
    )
