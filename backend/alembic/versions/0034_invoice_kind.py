"""Two bills, not one: a finished piece, and a parcel of loose stones.

The shop writes two documents and the system knew one. They are not the same
bill with some columns left blank.

A **finished product** is billed on its metal — weight, purity, wastage, and a
discount argued in ratti against that weight — with the stones priced alongside
and a photograph of the article on the customer's copy:

    Sr | Product code | Product name | Gold weight | Discount |
    Diamond CT | Diamond price | Amount | Image

**Loose material** is a parcel of stones and nothing else. No gold column, no
wastage, and — the part that makes this a kind rather than a print option — the
discount argues against the *stone price* instead of the gold weight:

    Sr | Product code | Product name | Diamond CT | Diamond price |
    Discount | Amount

That difference is why `kind` is stored on the document rather than inferred
from whether the lines happen to carry gold. A bill showing a ratti discount on
a parcel of diamonds claims a giveaway on metal that was never sold, and the
margin report files it under the wrong lever — it would show the shop
discounting gold on a sale containing none. The schema refuses gold weight,
wastage and ratti on a loose bill for the same reason.

Every existing invoice is a finished-product bill, which is what the system
could write, so the backfill is a default rather than a guess.

Revision ID: 0034_invoice_kind
Revises: 0033_cash_book
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_invoice_kind"
down_revision: Union[str, None] = "0033_cash_book"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

invoice_kind = postgresql.ENUM(
    "finished_product", "loose_material", name="invoice_kind", create_type=False
)


def upgrade() -> None:
    invoice_kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "invoices",
        sa.Column("kind", invoice_kind, nullable=False, server_default="finished_product"),
    )
    op.create_index("ix_invoices_kind", "invoices", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_invoices_kind", table_name="invoices")
    op.drop_column("invoices", "kind")
    invoice_kind.drop(op.get_bind(), checkfirst=True)
