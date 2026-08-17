"""Bills that charge gold in grams instead of rupees.

The shop writes two kinds of invoice and the system only knew one of them.

At the counter, gold is priced: ten grams at the day's rate, plus the stones,
plus the making, and the customer settles a single rupee figure.

With another jeweller the metal is never priced. The bill says how many fine
grams to hand over, and cash is owed only for the stones and the making. The
rate is agreed on the day the metal actually moves — printing one when the bill
is written would quote a price nobody accepted, and charging the gold in rupees
as well would bill for the same metal twice.

Three columns carry that:

* `customers.is_trade` — which kind of buyer this is. The shop was clear it
  never varies by deal: always grams for jewellers, always rupees at the
  counter. So the bill takes it from the customer instead of asking.
* `invoices.gold_charged_in` — the same choice, snapshotted onto the document.
  Reclassifying a customer next year must not rewrite what last year's bills
  meant, or what they posted.
* `invoices.metal_due_fine_g` — the grams the buyer must hand over, which is
  the obligation itself and posts against account 1215.

Every existing row defaults to the counter behaviour, so nothing already on the
books changes: `is_trade` false, `gold_charged_in` rupees, `metal_due_fine_g`
zero. Reversible in full.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_trade_billing"
down_revision: Union[str, None] = "0025_tunch_and_party_metal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

gold_charge = postgresql.ENUM("rupees", "grams", name="gold_charge", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    # Created explicitly before the column that uses it. `create_type=False` on
    # the column then stops SQLAlchemy emitting a second CREATE TYPE and failing
    # on the duplicate.
    gold_charge.create(bind, checkfirst=True)

    op.add_column(
        "customers",
        sa.Column("is_trade", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_customers_is_trade", "customers", ["is_trade"])

    op.add_column(
        "invoices",
        sa.Column(
            "gold_charged_in",
            gold_charge,
            nullable=False,
            server_default="rupees",
        ),
    )
    op.create_index("ix_invoices_gold_charged_in", "invoices", ["gold_charged_in"])
    op.add_column(
        "invoices",
        sa.Column(
            "metal_due_fine_g",
            sa.Numeric(14, 4),
            nullable=False,
            server_default="0",
        ),
    )
    # Metal owed is an amount handed over, never a credit. A negative figure
    # here would post the shop paying gold out on a sales invoice.
    op.create_check_constraint(
        "ck_invoices_metal_due_non_negative", "invoices", "metal_due_fine_g >= 0"
    )

    # A rupee bill has no metal obligation by definition — the gold was paid
    # for in money. Enforced rather than trusted to the application, because a
    # row that breaks it is a customer being billed for the same gold twice.
    op.create_check_constraint(
        "ck_invoices_metal_only_on_trade_bills",
        "invoices",
        "gold_charged_in = 'grams' OR metal_due_fine_g = 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoices_metal_only_on_trade_bills", "invoices", type_="check")
    op.drop_constraint("ck_invoices_metal_due_non_negative", "invoices", type_="check")
    op.drop_column("invoices", "metal_due_fine_g")
    op.drop_index("ix_invoices_gold_charged_in", table_name="invoices")
    op.drop_column("invoices", "gold_charged_in")
    op.drop_index("ix_customers_is_trade", table_name="customers")
    op.drop_column("customers", "is_trade")
    gold_charge.drop(op.get_bind(), checkfirst=True)
