from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.product import ProductStatus
from app.schemas.common import TimestampedRead
from app.schemas.product_stone import ProductStoneRead


class ProductBase(BaseModel):
    serial_no: str | None = Field(default=None, max_length=50, description="Auto-generated when omitted on create.")
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = None
    gold_weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    gold_purity: int | None = Field(default=None, ge=1, le=24)
    stone_weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    image_url: str | None = Field(default=None, max_length=500)
    total_cost: Decimal = Field(default=Decimal("0"), ge=0)
    material_cost: Decimal = Field(default=Decimal("0"), ge=0)
    status: ProductStatus = ProductStatus.in_production


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    serial_no: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = None
    gold_weight_g: Decimal | None = Field(default=None, ge=0)
    gold_purity: int | None = Field(default=None, ge=1, le=24)
    stone_weight_ct: Decimal | None = Field(default=None, ge=0)
    image_url: str | None = Field(default=None, max_length=500)
    total_cost: Decimal | None = Field(default=None, ge=0)
    material_cost: Decimal | None = Field(default=None, ge=0)
    status: ProductStatus | None = None


class ProductRead(TimestampedRead, ProductBase):
    stones: list[ProductStoneRead] = Field(default_factory=list)
    # Read-only: locked by the costing service on the first pass, never set by
    # the caller. Exposed so the UI can show what rate a piece was costed at.
    gold_rate_at_cost: Decimal | None = None
    # Set by the stock form. Lets a sale be traced back through every department
    # that touched the piece, which is the question the shop asks when a
    # customer returns one.
    design_id: int | None = None
    gross_weight_g: Decimal | None = None
    other_charges: Decimal = Decimal("0")
    stocked_at: datetime | None = None
