from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, require_perm
from app.models.product import Product
from app.models.product_stone import ProductStone
from app.models.stone import Stone
from app.schemas.product_stone import ProductStoneCreate, ProductStoneRead

router = APIRouter()
write = Depends(require_perm("product_stone:write"))
read = Depends(require_perm("product:read"))


@router.get(
    "/{product_id}/stones",
    response_model=list[ProductStoneRead],
    dependencies=[read],
)
async def list_product_stones(product_id: int, db: DbSession) -> list[ProductStone]:
    if (await db.get(Product, product_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    stmt = (
        select(ProductStone)
        .where(ProductStone.product_id == product_id)
        .order_by(ProductStone.id)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/{product_id}/stones",
    response_model=ProductStoneRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def attach_stone(
    product_id: int, payload: ProductStoneCreate, db: DbSession
) -> ProductStone:
    if (await db.get(Product, product_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    stone = await db.get(Stone, payload.stone_id)
    if stone is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid stone_id")

    rate = (
        payload.rate_per_ct
        if payload.rate_per_ct is not None
        else (Decimal(str(stone.default_rate_per_ct or 0)))
    )

    ps = ProductStone(
        product_id=product_id,
        stone_id=stone.id,
        quantity=payload.quantity,
        weight_ct=payload.weight_ct,
        rate_per_ct=rate,
        notes=payload.notes,
    )
    db.add(ps)
    await db.commit()
    await db.refresh(ps)
    return ps


@router.delete(
    "/{product_id}/stones/{ps_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[write],
)
async def detach_stone(product_id: int, ps_id: int, db: DbSession) -> None:
    ps = await db.get(ProductStone, ps_id)
    if ps is None or ps.product_id != product_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product stone not found")
    await db.delete(ps)
    await db.commit()
