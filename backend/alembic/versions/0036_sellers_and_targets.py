"""Salesmen, brokers, the bills credited to them, and targets to hit.

Three things arrive together because none of them is useful alone: a target
with nobody to hold it, a salesman with no bills attributed, or bills
attributed to nobody are each half a feature.

**Sellers.** A salesman carries the shop's stock out and sells on the road; the
pieces in his bag are the shop's until they sell. A broker introduces a buyer,
takes a cut, and never holds anything. One table because everything asked of
them is identical — a target, the bills they brought, what they earned — and
one flag because they settle differently, and a report that blended them would
show the shop carrying stock with a man who has never held any.

Deliberately not `vendors`. A karigar is given metal to transform and owes it
back as pieces; a salesman is given finished pieces and owes them back as goods
or money; a broker is given nothing. Three obligations in three units.
`PartyType.salesman` has been reserved in the ledger since the beginning,
waiting for exactly this.

**Bills carry their seller.** On the invoice rather than derived from the
customer: the same customer can be brought in by different people over time,
and a target credited to the wrong one is worse than no target.

**Targets in money and weight, side by side, either optional.** A gold business
manages in both and they answer different questions — a month where the rate
rose eight percent beats a rupee target on flat trading, and a weight target
says nothing about the stones or the making, which on some pieces is most of
the margin. Forcing one would make the report lie in whichever direction the
shop does not manage in.

A period is two dates, not a month. Monthly and annual are the common cases and
both are just a start and an end; a season, a wedding month, the eleven days
before Eid are the same shape. Storing a month would have made those
unrecordable and gained nothing.

Actuals are never stored. They are read off the invoices in the period every
time a target is asked about, so a target cannot drift from the sales it
measures — which a cached figure does the first time a bill is voided.

Revision ID: 0036_sellers_targets
Revises: 0035_pieces_base
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_sellers_targets"
down_revision: Union[str, None] = "0035_pieces_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

seller_kind = postgresql.ENUM("salesman", "broker", name="seller_kind", create_type=False)
target_scope = postgresql.ENUM(
    "company", "customer", "seller", name="target_scope", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    seller_kind.create(bind, checkfirst=True)
    target_scope.create(bind, checkfirst=True)

    op.create_table(
        "sellers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("kind", seller_kind, nullable=False, server_default="salesman"),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("cnic", sa.String(20), nullable=True),
        sa.Column("commission_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    for col in ("name", "kind", "cnic", "is_active"):
        op.create_index(f"ix_sellers_{col}", "sellers", [col])

    op.create_table(
        "sales_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", target_scope, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("seller_id", sa.Integer(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("label", sa.String(80), nullable=True),
        # Both nullable: set whichever the shop actually manages to and leave
        # the other empty. Progress is shown only against what was set.
        sa.Column("target_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("target_weight_g", sa.Numeric(14, 4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # CASCADE: a target belongs to the party it is set for and means
        # nothing without them. Unlike a purchase or a posting, deleting it
        # loses no history — the sales it measured are still on the invoices.
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"], ondelete="CASCADE"),
        # A period that ends before it starts measures nothing and would
        # silently report zero against every target set that way.
        sa.CheckConstraint("period_end >= period_start", name="ck_sales_targets_period"),
        # A target with neither figure is a row that cannot be missed or met.
        sa.CheckConstraint(
            "target_amount IS NOT NULL OR target_weight_g IS NOT NULL",
            name="ck_sales_targets_has_a_figure",
        ),
        # The scope decides which party column is filled, and exactly one is.
        # Without this a "customer" target naming a seller would quietly measure
        # the wrong party's sales.
        sa.CheckConstraint(
            "(scope = 'company' AND customer_id IS NULL AND seller_id IS NULL)"
            " OR (scope = 'customer' AND customer_id IS NOT NULL AND seller_id IS NULL)"
            " OR (scope = 'seller' AND seller_id IS NOT NULL AND customer_id IS NULL)",
            name="ck_sales_targets_scope_party",
        ),
    )
    for col in ("scope", "customer_id", "seller_id", "period_start", "period_end"):
        op.create_index(f"ix_sales_targets_{col}", "sales_targets", [col])

    op.add_column("invoices", sa.Column("seller_id", sa.Integer(), nullable=True))
    op.create_index("ix_invoices_seller_id", "invoices", ["seller_id"])
    # SET NULL rather than RESTRICT: removing a salesman who left should not be
    # blocked by every bill he ever brought, and the bill itself is unaffected —
    # it loses an attribution, not a figure.
    op.create_foreign_key(
        "fk_invoices_seller_id", "invoices", "sellers", ["seller_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_invoices_seller_id", "invoices", type_="foreignkey")
    op.drop_index("ix_invoices_seller_id", table_name="invoices")
    op.drop_column("invoices", "seller_id")
    op.drop_table("sales_targets")
    op.drop_table("sellers")
    target_scope.drop(op.get_bind(), checkfirst=True)
    seller_kind.drop(op.get_bind(), checkfirst=True)
