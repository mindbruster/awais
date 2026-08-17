from datetime import date

from sqlalchemy import Date, Enum, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.currency import Currency
from app.models.metal import Metal
from app.models.mixins import TimestampMixin


class GoldRate(Base, TimestampMixin):
    """
    A day's metal rate. Gold, and — since the shop buys both — silver.

    Stored at a reference purity and a currency. The pricing engine multiplies
    by `purity/24` for non-24k gold items.

    Multiple rates per (date, currency, metal, purity) are allowed — the system
    always uses the most recent one that has actually taken effect.

    The table keeps its name. Renaming it would rewrite every reference in the
    codebase and every saved query the shop has, to say something the `metal`
    column already says.
    """

    __tablename__ = "gold_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, index=True
    )
    # Which metal this rate prices. Gold unless said otherwise, so every row
    # written before silver existed reads correctly without being touched.
    metal: Mapped[Metal] = mapped_column(
        Enum(Metal, name="metal"), nullable=False, default=Metal.gold, index=True
    )
    rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    # Karat, and therefore gold only — the column is bounded at 24 everywhere
    # it is accepted. Silver is quoted out of a thousand and cannot be
    # expressed on this scale at all, which is what `fineness_pct` is for.
    purity: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    # The purity this rate is quoted *at*, as a percentage of pure, for metals
    # the karat scale cannot describe. 99.9 for 999 silver.
    #
    # It matters because the ledger holds metal in fine grams and values it at
    # rupees per fine gram, while the shop quotes "999 silver, Rs 340 a gram".
    # Those differ by a tenth of a percent — small per gram, and not small
    # across a few kilos of silver. `fine_rate_per_g` does that division in one
    # place rather than leaving each call site to forget it.
    #
    # Null on gold rows, where the karat already says it.
    fineness_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    notes: Mapped[str | None] = mapped_column(String(255))
