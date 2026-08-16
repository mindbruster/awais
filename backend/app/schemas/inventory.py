from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.inventory import InventoryType
from app.schemas.common import TimestampedRead


class InventoryItemBase(BaseModel):
    type: InventoryType
    label: str = Field(min_length=1, max_length=150)
    location: str | None = Field(default=None, max_length=100)
    quantity: int = Field(default=0, ge=0)
    weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    purity: int | None = Field(default=None, ge=1, le=24)
    product_id: int | None = None


class InventoryItemCreate(InventoryItemBase):
    # Which shop this belongs to. Optional: left unset it falls back to the
    # user's own branch, then to the default, so a single-shop business
    # never sees the field and a multi-shop one can be explicit.
    branch_id: int | None = None
    pass


class InventoryItemUpdate(BaseModel):
    type: InventoryType | None = None
    label: str | None = Field(default=None, min_length=1, max_length=150)
    location: str | None = Field(default=None, max_length=100)
    quantity: int | None = Field(default=None, ge=0)
    weight_g: Decimal | None = Field(default=None, ge=0)
    weight_ct: Decimal | None = Field(default=None, ge=0)
    purity: int | None = Field(default=None, ge=1, le=24)
    product_id: int | None = None


class InventoryItemRead(TimestampedRead, InventoryItemBase):
    # Which shop holds this. Always set on a stored row, so the client can
    # show and filter by it without a second lookup.
    branch_id: int | None = None

