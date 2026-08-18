from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.inventory import InventoryItem, InventoryType
from app.models.stock_movement import MovementType, StockMovement
from app.schemas.stock_movement import StockMovementCreate, StockMovementRead
from app.services.inventory import post_movement
from app.services.ledger import d

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
    "",
    response_model=StockMovementRead,
    status_code=status.HTTP_201_CREATED,
    # Direct stock adjustments bypass the manufacturing/sales audit trail, so we
    # gate them with password confirmation regardless of role.
    dependencies=[write, Depends(require_password_confirm)],
)
async def create_movement(
    payload: StockMovementCreate, db: DbSession, current: CurrentUser
) -> StockMovement:
    item = await db.get(InventoryItem, payload.inventory_item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")

    # Metal is refused here, and this is the last of four doors that let stock
    # move without the books hearing about it.
    #
    # A movement written straight to a melt pot updates the shelf and nothing
    # else, so 1130 Gold in Hand and the pot immediately disagree — and neither
    # of them says which is right. The other three doors were `POST` and
    # `PATCH /inventory`, both now closed, and returned metal landing in a pot
    # of the wrong purity, now routed properly.
    #
    # There is a correct way to change what a pot holds, and it is a stock
    # count: it posts the movement *and* the journal entry in one transaction,
    # carries a reason, and can require a second signature. Everything this
    # endpoint was used for on metal, that does better.
    #
    # Stones and finished goods still pass: their inventory is carried in money
    # at cost and a carat adjustment does not move a metal control account.
    if item.type in (InventoryType.raw_gold, InventoryType.raw_silver) and (
        d(payload.weight_g_delta) != 0
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Metal cannot be adjusted directly — it would move the shelf without "
            "moving the books, and the two would disagree with nothing to say which "
            "is right. Count the pot instead: Reconciliation posts both halves "
            "together, with a reason on it.",
        )

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
