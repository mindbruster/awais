from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.stock_movement import MovementType
from app.schemas.common import TimestampedRead


class StockMovementCreate(BaseModel):
    inventory_item_id: int
    type: MovementType
    quantity_delta: int = 0
    weight_g_delta: Decimal = Decimal("0")
    weight_ct_delta: Decimal = Decimal("0")
    reference_type: str | None = Field(default=None, max_length=50)
    reference_id: int | None = None
    notes: str | None = None


class StockMovementRead(TimestampedRead):
    type: MovementType
    inventory_item_id: int
    quantity_delta: int
    weight_g_delta: Decimal
    weight_ct_delta: Decimal
    reference_type: str | None = None
    reference_id: int | None = None
    notes: str | None = None
    created_by_user_id: int | None = None
