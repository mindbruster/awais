import enum

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.branch import Branch
from app.models.mixins import TimestampMixin
from app.models.product import Product


class InventoryType(str, enum.Enum):
    raw_gold = "raw_gold"
    # Bought pure at 999, given to the same workers, and never interchangeable
    # with the gold beside it. Its own category so that "how much gold do I
    # have" cannot quietly include eight kilos of silver.
    raw_silver = "raw_silver"
    raw_stone = "raw_stone"
    # Stones chipped in the setting and handed back.
    #
    # Its own category rather than a smaller figure in `raw_stone`, because
    # broken material is not interchangeable with whole material: it cannot be
    # issued to a setter for the piece it was bought for, and counting it in
    # "how much 12 PTR do I have" would promise stones that cannot do the job.
    # It is still stock and still carried at cost — chipped diamonds sell — so
    # it is not a write-off either. Nothing is lost until it is disposed of.
    broken_stone = "broken_stone"
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
    # Fineness in percent, preferred over the karat integer above. Bullion is
    # bought on an assayed tunch — 99.5, 99.9 — which karat cannot express at
    # all. See `Product.gold_tunch_pct`.
    tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"),
        index=True,
    )
    product: Mapped[Product | None] = relationship(lazy="joined")

    # Which shop holds this stock. Not nullable: "we have 400g of 22k" is not
    # an answer once there is more than one counter, and a row that cannot say
    # where it sits cannot be counted at either.
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch: Mapped[Branch] = relationship(lazy="joined")
