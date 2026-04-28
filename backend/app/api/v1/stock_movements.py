from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_perm
from app.models.inventory import InventoryItem
from app.models.stock_movement import MovementType, StockMovement
from app.schemas.stock_movement import StockMovementCreate, StockMovementRead
from app.services.inventory import post_movement

router = APIRouter()
read = Depends(require_perm("stock_movement:read"))
write = Depends(require_perm("stock_movement:write"))


@router.get("", response_model=list[StockMovementRead], dependencies=[read])
async def list_movements(
    db: DbSession,
    inventory_item_id: int | None = Query(default=None),
    type: MovementType | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[StockMovement]:
    stmt = select(StockMovement).order_by(StockMovement.id.desc()).limit(limit).offset(offset)
    if inventory_item_id is not None:
        stmt = stmt.where(StockMovement.inventory_item_id == inventory_item_id)
    if type is not None:
        stmt = stmt.where(StockMovement.type == type)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "", response_model=StockMovementRead, status_code=status.HTTP_201_CREATED, dependencies=[write]
)
async def create_movement(
    payload: StockMovementCreate, db: DbSession, current: CurrentUser
) -> StockMovement:
    item = await db.get(InventoryItem, payload.inventory_item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")

    movement = await post_movement(
        db,
        item=item,
        type=payload.type,
        quantity_delta=payload.quantity_delta,
        weight_g_delta=payload.weight_g_delta,
        weight_ct_delta=payload.weight_ct_delta,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
        notes=payload.notes,
        user_id=current.id,
    )
    await db.commit()
    await db.refresh(movement)
    return movement
