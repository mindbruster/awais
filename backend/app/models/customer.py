from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.location import City, Country
from app.models.mixins import TimestampMixin


class Customer(Base, TimestampMixin):
    """
    A buyer.

    Only `name` is required, deliberately. Customers in this trade decline to
    hand over identity documents and phone numbers at the counter, and a form
    that insists on them just gets filled with junk — so everything else is
    optional and captured when it's offered.
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    # The shop's own ledger number for this account, printed on their bills.
    # Free text and optional: it comes off whatever book the business kept
    # before this system, and half the retail customers will never have one.
    account_no: Mapped[str | None] = mapped_column(String(30), index=True)
    # Another jeweller, rather than somebody buying across the counter.
    #
    # This single flag decides the shape of every bill they are given. A trade
    # buyer settles the metal in metal — the invoice tells him how many fine
    # grams to hand over and never prices them — and pays cash only for stones
    # and making. A counter customer pays rupees for the lot.
    #
    # Held on the customer rather than asked per bill because the shop was clear
    # that it never varies: always grams for jewellers, always rupees at the
    # counter. Asking every time would be a question with one right answer and
    # a way to get it wrong. Each invoice still snapshots the resulting choice,
    # so reclassifying a customer never rewrites their old bills.
    is_trade: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(30), index=True)
    phone2: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    cnic: Mapped[str | None] = mapped_column(String(20), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    # Who introduced them — this trade runs on referral and the shop tracks it.
    reference: Mapped[str | None] = mapped_column(String(150))

    # Used to prompt the shop to reach out; a birthday or anniversary message
    # is a standard sales motion here.
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    anniversary: Mapped[date | None] = mapped_column(Date)

    city_id: Mapped[int | None] = mapped_column(
        ForeignKey("cities.id", ondelete="SET NULL"), index=True
    )
    city: Mapped[City | None] = relationship(lazy="joined")
    country_id: Mapped[int | None] = mapped_column(
        ForeignKey("countries.id", ondelete="SET NULL"), index=True
    )
    country: Mapped[Country | None] = relationship(lazy="joined")

    # Balance carried in from whatever the shop used before. Positive means the
    # customer owes the shop. Superseded by an opening journal entry once the
    # ledger lands; kept as the record of what was declared at go-live.
    opening_balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)

    # Read-side conveniences so customer lists render the place names without a
    # second lookup per row. Both relationships are eagerly joined.
    @property
    def city_name(self) -> str | None:
        return self.city.name if self.city else None

    @property
    def country_name(self) -> str | None:
        return self.country.name if self.country else None
