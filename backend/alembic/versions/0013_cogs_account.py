"""Add a cost-of-goods-sold head.

Stocking a piece debits 1150 Finished Goods and credits 1130 Gold in Hand, so
the metal stops being issuable bullion and becomes a sellable asset. Selling it
had no counterpart: the invoice posted revenue against the customer and nothing
relieved 1150, so the books' finished-goods balance grew with every sale and
never came back down. Within a month the ledger would claim the shop was
holding every piece it had ever sold.

The reason it was left open is that there was no head to post the cost to, and
inventing a number against an unrelated account would have been worse. This
adds the head.

Revision ID: 0013_cogs_account
Revises: 0012_sales_purchasing
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_cogs_account"
down_revision: Union[str, None] = "0012_sales_purchasing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO accounts (code, name, type, parent_id, is_system, is_postable, is_active)
        SELECT '5400', 'Cost of Goods Sold', CAST('expense' AS account_type),
               (SELECT id FROM accounts WHERE code = '5000'), TRUE, TRUE, TRUE
        WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE code = '5400')
        """
    )


def downgrade() -> None:
    # Only if nothing has been posted to it — dropping an account with lines
    # would orphan them and break every statement that walks the tree.
    op.execute(
        """
        DELETE FROM accounts
        WHERE code = '5400'
          AND NOT EXISTS (
              SELECT 1 FROM journal_lines jl
              JOIN accounts a ON a.id = jl.account_id
              WHERE a.code = '5400'
          )
        """
    )
