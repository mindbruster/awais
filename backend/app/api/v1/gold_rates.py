from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select

from app.api.deps import DbSession, require_perm
from app.models.currency import Currency
from app.models.gold_rate import GoldRate
from app.models.exchange_rate import ExchangeRate
from app.schemas.gold_rate import (
    ExchangeRateCreate,
    ExchangeRateRead,
    GoldRateCreate,
    GoldRateRead,
)
from app.services.fx import rate_in_force as fx_rate_in_force
from app.services.gold_rate import rate_in_force

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
    """The rate in force today for (currency, purity). 404 if none set yet.

    A rate keyed in advance for a future date is deliberately not "current" —
    see `app.services.gold_rate.rate_in_force`.
    """
    rate = await rate_in_force(db, currency=currency, purity=purity)
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


# --------------------------------------------------------------------------
# Exchange rates
# --------------------------------------------------------------------------
# Mounted under the same router as gold rates because they are the same job to
# the person doing it: the two numbers that have to be right before anything
# can be priced today.
@router.get("/fx", response_model=list[ExchangeRateRead], dependencies=[read])
async def list_exchange_rates(
    db: DbSession,
    currency: Currency | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ExchangeRate]:
    stmt = (
        select(ExchangeRate)
        .order_by(desc(ExchangeRate.rate_date), desc(ExchangeRate.id))
        .limit(limit)
        .offset(offset)
    )
    if currency:
        stmt = stmt.where(ExchangeRate.currency == currency)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/fx/current", response_model=ExchangeRateRead, dependencies=[read])
async def current_exchange_rate(
    db: DbSession, currency: Currency = Query(default=Currency.USD)
) -> ExchangeRate:
    """
    The rate in force today. A rate keyed for a future date is a plan, not a
    price, and is deliberately not returned here — see `services/fx.py`.
    """
    if currency is Currency.PKR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "PKR is the book currency and converts to itself at 1.",
        )
    rate = await fx_rate_in_force(db, currency)
    if rate is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No {currency.value} rate has taken effect yet.",
        )
    row = (
        await db.execute(
            select(ExchangeRate)
            .where(ExchangeRate.currency == currency, ExchangeRate.pkr_per_unit == rate)
            .order_by(desc(ExchangeRate.rate_date), desc(ExchangeRate.id))
            .limit(1)
        )
    ).scalar_one()
    return row


@router.post(
    "/fx", response_model=ExchangeRateRead, status_code=status.HTTP_201_CREATED, dependencies=[write]
)
async def create_exchange_rate(payload: ExchangeRateCreate, db: DbSession) -> ExchangeRate:
    row = ExchangeRate(**payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
