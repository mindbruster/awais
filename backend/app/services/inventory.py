from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem
from app.models.stock_movement import MovementType, StockMovement


async def post_movement(
    db: AsyncSession,
    *,
    item: InventoryItem,
    type: MovementType,
    quantity_delta: int = 0,
    weight_g_delta: Decimal | float = 0,
    weight_ct_delta: Decimal | float = 0,
    reference_type: str | None = None,
    reference_id: int | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> StockMovement:
    """
    Atomically record a movement and update the inventory snapshot.
    Caller is responsible for committing the surrounding transaction.
    """
    qd = int(quantity_delta or 0)
    wg = Decimal(str(weight_g_delta or 0))
    wc = Decimal(str(weight_ct_delta or 0))

    new_qty = item.quantity + qd
    new_wg = Decimal(str(item.weight_g)) + wg
    new_wc = Decimal(str(item.weight_ct)) + wc

    if new_qty < 0 or new_wg < 0 or new_wc < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient stock on item #{item.id}: would result in "
                f"qty={new_qty}, weight_g={new_wg}, weight_ct={new_wc}"
            ),
        )

    item.quantity = new_qty
    item.weight_g = new_wg
    item.weight_ct = new_wc

    movement = StockMovement(
        type=type,
        inventory_item_id=item.id,
        quantity_delta=qd,
        weight_g_delta=wg,
        weight_ct_delta=wc,
        reference_type=reference_type,
        reference_id=reference_id,
        notes=notes,
        created_by_user_id=user_id,
    )
    db.add(movement)
    await db.flush()
    return movement
