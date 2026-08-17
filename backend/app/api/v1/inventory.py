from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.services import branches
from app.models.inventory import InventoryItem, InventoryType
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
)

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
    item_id: int, payload: InventoryItemUpdate, db: DbSession
) -> InventoryItem:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
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
