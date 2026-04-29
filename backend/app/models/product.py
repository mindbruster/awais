import enum

from sqlalchemy import Enum, Integer, Numeric, String, Text
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

    # Phase 7 — total making cost rolled up from manufacturing job (labor + polish
    # + stone fixing + other). Material value is tracked separately on
    # `material_cost` so that profit = revenue − (material + labor).
    total_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    # Capitalised material value: gold value at completion + sum of stones.
    # Recomputed when stones are attached/detached. Zero for products that
    # weren't created via the manufacturing pipeline.
    material_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

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
