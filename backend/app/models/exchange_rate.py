from datetime import date

from sqlalchemy import Date, Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.currency import Currency
from app.models.mixins import TimestampMixin


class ExchangeRate(Base, TimestampMixin):
    """
    What a foreign currency is worth in rupees on a given day.

    PKR is the book currency. That is a deliberate choice, not an oversight: a
    shop keeps one set of books, and every balance, statement and report has to
    add up in a single unit or none of them mean anything. Dealing in dollars
    does not change that — it changes what has to be converted, and at which
    rate, and when.

    The rate is stored per day and snapshotted onto every journal line it
    values, exactly as the gold rate is. A dollar invoice raised in March stays
    valued at March's rate forever; re-translating it whenever the rupee moves
    would silently rewrite last quarter's profit.

    Multiple rates per day are allowed and the latest one entered wins, which is
    how the counter works when the rate moves between morning and afternoon.
    """

    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The foreign currency. PKR never appears here — it is the base, and a row
    # saying "1 PKR = 1 PKR" is noise that invites a bug where someone converts
    # rupees to rupees at a rate that isn't 1.
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, index=True
    )
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Rupees per one unit of `currency`. Named for the direction so nobody has
    # to guess which way to multiply.
    pkr_per_unit: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(255))
