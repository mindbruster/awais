import enum

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.product import Product


class InventoryType(str, enum.Enum):
    raw_gold = "raw_gold"
    raw_stone = "raw_stone"
    finished_product = "finished_product"
    other = "other"


class InventoryItem(Base, TimestampMixin):
    """
    Generic stock record. For raw materials (gold/stone), product_id is NULL and
    weight/purity carry the data. For finished pieces, product_id links to a Product
    and quantity is typically 1.
    """

    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[InventoryType] = mapped_column(
        Enum(InventoryType, name="inventory_type"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    location: Mapped[str | None] = mapped_column(String(100))

    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weight_g: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    weight_ct: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    purity: Mapped[int | None] = mapped_column(Integer)  # for raw_gold

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
    )
    product: Mapped[Product | None] = relationship(lazy="joined")
