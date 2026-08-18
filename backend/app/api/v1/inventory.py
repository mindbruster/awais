from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.services import branches
from app.models.inventory import InventoryItem, InventoryType
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
    OpeningStockCreate,
)
from app.services import opening_stock
from app.services.audit import changes, log_action, snapshot

router = APIRouter()
read = Depends(require_perm("inventory:read"))
write = Depends(require_perm("inventory:write"))
delete = Depends(require_perm("inventory:delete"))


@router.get("", response_model=list[InventoryItemRead], dependencies=[read])
async def list_items(
    db: DbSession,
    q: str | None = Query(default=None),
    type: InventoryType | None = Query(default=None),
    branch_id: int | None = Query(default=None, description="Stock held at this shop"),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[InventoryItem]:
    stmt = select(InventoryItem).order_by(InventoryItem.id.desc()).limit(limit).offset(offset)
    if type:
        stmt = stmt.where(InventoryItem.type == type)
    if branch_id is not None:
        stmt = stmt.where(InventoryItem.branch_id == branch_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(InventoryItem.label.ilike(like), InventoryItem.location.ilike(like)))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=InventoryItemRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_item(
    payload: InventoryItemCreate, db: DbSession, current: CurrentUser
) -> InventoryItem:
    data = payload.model_dump()
    branch = await branches.resolve_branch(
        db, requested_id=data.pop("branch_id", None), user=current
    )
    item = InventoryItem(**data, branch_id=branch.id)
    db.add(item)
    await db.flush()
    await log_action(
        db,
        user=current,
        action="inventory.create",
        resource_type="inventory_item",
        resource_id=item.id,
        after=snapshot(item),
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/{item_id}", response_model=InventoryItemRead, dependencies=[read])
async def get_item(item_id: int, db: DbSession) -> InventoryItem:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")
    return item


@router.patch("/{item_id}", response_model=InventoryItemRead, dependencies=[write])
async def update_item(
    item_id: int, payload: InventoryItemUpdate, db: DbSession, current: CurrentUser
) -> InventoryItem:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")
    was = snapshot(item)
    # Only the describing fields reach here — `InventoryItemUpdate` no longer
    # carries a weight or a quantity, so no amount of payload can move a
    # balance through this endpoint.
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    before, after = changes(was, snapshot(item))
    if before or after:
        await log_action(
            db,
            user=current,
            action="inventory.update",
            resource_type="inventory_item",
            resource_id=item.id,
            before=before,
            after=after,
        )
    await db.commit()
    await db.refresh(item)
    return item


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[delete, Depends(require_password_confirm)],
)
async def delete_item(item_id: int, db: DbSession) -> None:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")
    await db.delete(item)
    await db.commit()


@router.post(
    "/{item_id}/opening",
    response_model=InventoryItemRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write, Depends(require_password_confirm)],
)
async def record_opening_stock(
    item_id: int, payload: OpeningStockCreate, db: DbSession, current: CurrentUser
) -> InventoryItem:
    """
    Record what a pot held on the day the shop started using this system.

    The only way to put a quantity into stock without a purchase behind it, and
    it is still a document: the material goes into its asset account and the
    same value into 3200 Opening Balance Equity, so the shelf and the books
    start life agreeing.

    Behind a password because it is the one endpoint that can create value out
    of a declaration. Once per pot — a second is a correction, and corrections
    are counts, which carry a reason and can require a second signature.
    """
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")

    entry = await opening_stock.post_opening_stock(
        db,
        item,
        weight_g=payload.weight_g,
        weight_ct=payload.weight_ct,
        quantity=payload.quantity,
        rate_per_g=payload.rate_per_g,
        value=payload.value,
        as_of=payload.as_of,
        notes=payload.notes,
        user_id=current.id,
    )
    await log_action(
        db,
        user=current,
        action="inventory.opening_stock",
        resource_type="inventory_item",
        resource_id=item.id,
        details={
            "label": item.label,
            "weight_g": str(payload.weight_g),
            "weight_ct": str(payload.weight_ct),
            "entry_no": entry.entry_no,
        },
        reason=payload.notes,
        after=snapshot(item),
    )
    await db.commit()
    await db.refresh(item)
    return item
