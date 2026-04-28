from datetime import date

from sqlalchemy import Date, Enum, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.currency import Currency
from app.models.mixins import TimestampMixin


class GoldRate(Base, TimestampMixin):
    """
    Daily gold rate. Stored at a reference purity (24k by default) and a
    currency. The pricing engine multiplies by `purity/24` for non-24k items.

    Multiple rates per (date, currency, purity) are allowed — the system
    always uses the most recent one.
    """

    __tablename__ = "gold_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, index=True
    )
    rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    purity: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    notes: Mapped[str | None] = mapped_column(String(255))
