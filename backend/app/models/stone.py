import enum

from sqlalchemy import Enum, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.currency import Currency
from app.models.mixins import TimestampMixin


class StoneKind(str, enum.Enum):
    diamond = "diamond"
    ruby = "ruby"
    emerald = "emerald"
    sapphire = "sapphire"
    pearl = "pearl"
    other = "other"


class Stone(Base, TimestampMixin):
    """
    Master catalogue of stone *types* (not physical inventory). A stone here
    captures the qualitative attributes — kind, cut, color, clarity — and a
    default price. Inventory items and product-stone breakdowns reference these.
    """

    __tablename__ = "stones"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    kind: Mapped[StoneKind] = mapped_column(
        Enum(StoneKind, name="stone_kind"), nullable=False, index=True
    )
    # Free-form so you can store "round", "princess", "marquise", etc.
    cut: Mapped[str | None] = mapped_column(String(40))
    # GIA color grade or local label: D-Z for diamonds; for coloured stones use
    # whatever your shop uses ("vivid red", "royal blue").
    color: Mapped[str | None] = mapped_column(String(40))
    # GIA clarity grade or local label: FL, IF, VVS1, VVS2, VS1, VS2, SI1, SI2,
    # I1, I2, I3 — or anything for coloured stones.
    clarity: Mapped[str | None] = mapped_column(String(40))

    default_rate_per_ct: Mapped[float | None] = mapped_column(Numeric(14, 4))
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, default=Currency.PKR
    )

    notes: Mapped[str | None] = mapped_column(Text)
