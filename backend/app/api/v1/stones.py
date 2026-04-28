from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import DbSession, require_perm
from app.models.stone import Stone, StoneKind
from app.schemas.stone import StoneCreate, StoneRead, StoneUpdate

router = APIRouter()
read = Depends(require_perm("stone:read"))
write = Depends(require_perm("stone:write"))
delete = Depends(require_perm("stone:delete"))


@router.get("", response_model=list[StoneRead], dependencies=[read])
async def list_stones(
    db: DbSession,
    q: str | None = Query(default=None),
    kind: StoneKind | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Stone]:
    stmt = select(Stone).order_by(Stone.name).limit(limit).offset(offset)
    if kind:
        stmt = stmt.where(Stone.kind == kind)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Stone.name.ilike(like),
                Stone.cut.ilike(like),
                Stone.color.ilike(like),
                Stone.clarity.ilike(like),
            )
        )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=StoneRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_stone(payload: StoneCreate, db: DbSession) -> Stone:
    stone = Stone(**payload.model_dump())
    db.add(stone)
    await db.commit()
    await db.refresh(stone)
    return stone


@router.get("/{stone_id}", response_model=StoneRead, dependencies=[read])
async def get_stone(stone_id: int, db: DbSession) -> Stone:
    stone = await db.get(Stone, stone_id)
    if stone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stone not found")
    return stone


@router.patch("/{stone_id}", response_model=StoneRead, dependencies=[write])
async def update_stone(stone_id: int, payload: StoneUpdate, db: DbSession) -> Stone:
    stone = await db.get(Stone, stone_id)
    if stone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stone not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(stone, k, v)
    await db.commit()
    await db.refresh(stone)
    return stone


@router.delete("/{stone_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[delete])
async def delete_stone(stone_id: int, db: DbSession) -> None:
    stone = await db.get(Stone, stone_id)
    if stone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stone not found")
    await db.delete(stone)
    await db.commit()
