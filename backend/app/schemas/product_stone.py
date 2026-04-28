from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedRead
from app.schemas.stone import StoneRead


class ProductStoneCreate(BaseModel):
    stone_id: int
    quantity: int = Field(default=1, ge=1)
    weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    rate_per_ct: Decimal | None = Field(
        default=None,
        ge=0,
        description="If omitted, the stone's default rate is used.",
    )
    notes: str | None = None


class ProductStoneRead(TimestampedRead):
    product_id: int
    stone_id: int
    quantity: int
    weight_ct: Decimal
    rate_per_ct: Decimal
    notes: str | None = None
    stone: StoneRead
