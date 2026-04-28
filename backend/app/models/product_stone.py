from sqlalchemy import ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.stone import Stone


class ProductStone(Base, TimestampMixin):
    """
    Per-product stone breakdown — captures *which specific stones* (from the
    master catalogue) are mounted on a finished product, with the snapshot of
    the price applied. A product can have many of these.
    """

    __tablename__ = "product_stones"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stone_id: Mapped[int] = mapped_column(
        ForeignKey("stones.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stone: Mapped[Stone] = relationship(lazy="joined")

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    weight_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    rate_per_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    notes: Mapped[str | None] = mapped_column(Text)
