import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class ProductStatus(str, enum.Enum):
    in_stock = "in_stock"
    in_production = "in_production"
    sold = "sold"
    on_approval = "on_approval"


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    serial_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    description: Mapped[str | None] = mapped_column(Text)

    # Weights (precision: 4 decimal places — enough for grams & carats)
    gold_weight_g: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    gold_purity: Mapped[int | None] = mapped_column(Integer)  # 9, 14, 18, 22, 24
    stone_weight_ct: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)

    image_url: Mapped[str | None] = mapped_column(String(500))

    # Filled in by the stock form when a design leaves the workshop. Gross is
    # what the scale says with stones in; `gold_weight_g` above is the metal
    # alone, which is what gets priced.
    gross_weight_g: Mapped[float | None] = mapped_column(Numeric(12, 4))
    other_charges: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    stocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The piece this product came off, so a sale can be traced back through
    # every department that touched it.
    design_id: Mapped[int | None] = mapped_column(
        ForeignKey("designs.id", ondelete="SET NULL"), index=True
    )

    # Making cost: the labour of every leg the piece went through, plus any
    # other charges, rolled up by the stock form when the design is stocked.
    # Material is tracked separately on `material_cost` so that
    # profit = revenue − (material + making); collapsing the two would hide
    # which of the shop's two levers actually earned the money.
    total_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    # Capitalised material value: gold value when the piece was costed, plus the
    # stones. Recomputed when stones are attached or detached. Zero for a piece
    # that never went through the stock form — one bought in finished, or
    # already in the safe at go-live — which is what shows up on the margin
    # report as uncosted metal.
    material_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    # The gold rate this product's metal was capitalised at, locked on the first
    # costing pass and never revisited. Without it, recomputing material_cost
    # later (e.g. when a stone is attached) would silently re-price the gold at
    # the current rate and rewrite historical cost — and every profit figure
    # derived from it.
    gold_rate_at_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))

    # Per-product stone breakdown — owned by the product, cascade on delete.
    stones: Mapped[list["ProductStone"]] = relationship(  # noqa: F821
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, name="product_status"),
        default=ProductStatus.in_production,
        nullable=False,
        index=True,
    )
