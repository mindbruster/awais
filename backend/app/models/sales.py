import enum
from datetime import date

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.customer import Customer
from app.models.mixins import TimestampMixin


class SellerKind(str, enum.Enum):
    """
    Who is bringing the business.

    A **salesman** is the shop's own: he carries stock out to jewellers, sells
    on the road, and the pieces in his bag are still the shop's until they sell.
    A **broker** is not the shop's — he introduces a buyer and takes a cut of
    what results, and never holds anything.

    One table because everything asked of them is the same — a target, the
    bills credited to them, what they earned — and one flag because the two
    settle differently and a report that blended them would show the shop
    carrying stock with a man who has never held any.
    """

    salesman = "salesman"
    broker = "broker"


class Seller(Base, TimestampMixin):
    """
    A salesman or a broker, and what the shop owes them for bringing work.

    Deliberately not a `Vendor`. A karigar is given the shop's metal to
    transform and owes it back as pieces; a salesman is given finished pieces
    and owes them back as goods or money; a broker is given nothing at all.
    Those are three different obligations settling in three different units,
    and `PartyType.salesman` has existed in the ledger since the beginning
    waiting for exactly this.
    """

    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    kind: Mapped[SellerKind] = mapped_column(
        Enum(SellerKind, name="seller_kind"),
        nullable=False,
        default=SellerKind.salesman,
        index=True,
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    cnic: Mapped[str | None] = mapped_column(String(20), index=True)
    # What they earn on what they bring, as a percentage of the sale. Held here
    # rather than computed per bill because it is a standing arrangement; a bill
    # that needs a different rate is a negotiation, not a default.
    commission_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class TargetScope(str, enum.Enum):
    """Whose target this is."""

    company = "company"
    customer = "customer"
    seller = "seller"


class SalesTarget(Base, TimestampMixin):
    """
    A figure to hit, over a period, for the company or one party.

    **Money and weight, side by side, either optional.** A gold business
    manages in both and they answer different questions: a month where the rate
    rose eight percent can beat a rupee target on flat trading, and a weight
    target says nothing about the stones or the making, which on some pieces is
    most of the margin. Forcing one would make the report lie in whichever
    direction the shop does not manage in.

    **A period is two dates, not a month.** Monthly and annual are the common
    cases and both are just a start and an end; anything else — a season, a
    wedding month, the eleven days before Eid — is the same shape. Storing a
    month would have made those unrecordable and gained nothing.

    Actuals are never stored. They are read off the invoices in the period each
    time the target is asked about, so a target cannot drift from the sales it
    is measuring — which a cached figure inevitably does the first time a bill
    is voided.
    """

    __tablename__ = "sales_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[TargetScope] = mapped_column(
        Enum(TargetScope, name="target_scope"), nullable=False, index=True
    )
    # Exactly one of these is set, and which one is decided by `scope`. A
    # company target carries neither.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    customer: Mapped[Customer | None] = relationship(lazy="joined")
    seller_id: Mapped[int | None] = mapped_column(
        ForeignKey("sellers.id", ondelete="CASCADE"), index=True
    )
    seller: Mapped[Seller | None] = relationship(lazy="joined")

    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # A label the shop reads — "August 2026", "FY 25-26", "Eid". Free text
    # because the periods it names are not all months.
    label: Mapped[str | None] = mapped_column(String(80))

    # Both nullable: set whichever the shop actually manages to, leave the
    # other empty, and the report shows progress only against what was set.
    target_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    target_weight_g: Mapped[float | None] = mapped_column(Numeric(14, 4))

    notes: Mapped[str | None] = mapped_column(Text)
