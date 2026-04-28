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
    status: ProductStatus | None = None


class ProductRead(TimestampedRead, ProductBase):
    stones: list[ProductStoneRead] = Field(default_factory=list)
