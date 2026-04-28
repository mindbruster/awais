from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select

from app.api.deps import DbSession, require_perm
from app.models.currency import Currency
from app.models.gold_rate import GoldRate
from app.schemas.gold_rate import GoldRateCreate, GoldRateRead

router = APIRouter()
read = Depends(require_perm("gold_rate:read"))
write = Depends(require_perm("gold_rate:write"))


@router.get("", response_model=list[GoldRateRead], dependencies=[read])
async def list_rates(
    db: DbSession,
    currency: Currency | None = Query(default=None),
    purity: int | None = Query(default=None, ge=1, le=24),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[GoldRate]:
    stmt = (
        select(GoldRate)
        .order_by(desc(GoldRate.rate_date), desc(GoldRate.id))
        .limit(limit)
        .offset(offset)
    )
    if currency:
        stmt = stmt.where(GoldRate.currency == currency)
    if purity is not None:
        stmt = stmt.where(GoldRate.purity == purity)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/current", response_model=GoldRateRead, dependencies=[read])
async def current_rate(
    db: DbSession,
    currency: Currency = Query(default=Currency.PKR),
    purity: int = Query(default=24, ge=1, le=24),
) -> GoldRate:
    """Most recent rate for the given (currency, purity). 404 if none set yet."""
    stmt = (
        select(GoldRate)
        .where(GoldRate.currency == currency, GoldRate.purity == purity)
        .order_by(desc(GoldRate.rate_date), desc(GoldRate.id))
        .limit(1)
    )
    rate = (await db.execute(stmt)).scalar_one_or_none()
    if rate is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No gold rate set yet for {currency.value} at {purity}k.",
        )
    return rate


@router.post("", response_model=GoldRateRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_rate(payload: GoldRateCreate, db: DbSession) -> GoldRate:
    rate = GoldRate(**payload.model_dump())
    db.add(rate)
    await db.commit()
    await db.refresh(rate)
    return rate


@router.delete("/{rate_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[write])
async def delete_rate(rate_id: int, db: DbSession) -> None:
    rate = await db.get(GoldRate, rate_id)
    if rate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gold rate not found")
    await db.delete(rate)
    await db.commit()
