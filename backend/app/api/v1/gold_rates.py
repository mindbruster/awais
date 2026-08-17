from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select

from app.api.deps import CurrentUser, DbSession, require_perm
from app.services.audit import log_action, snapshot
from app.models.currency import Currency
from app.models.gold_rate import GoldRate
from app.models.exchange_rate import ExchangeRate
from app.models.metal import Metal
from app.schemas.gold_rate import (
    ExchangeRateCreate,
    ExchangeRateRead,
    GoldRateCreate,
    GoldRateRead,
    LiveMetalRates,
)
from app.services import metal_feed
from app.services.fx import rate_in_force as fx_rate_in_force
from app.services.gold_rate import rate_in_force

router = APIRouter()
read = Depends(require_perm("gold_rate:read"))
write = Depends(require_perm("gold_rate:write"))


@router.get("", response_model=list[GoldRateRead], dependencies=[read])
async def list_rates(
    db: DbSession,
    currency: Currency | None = Query(default=None),
    metal: Metal | None = Query(default=None),
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
    if metal is not None:
        stmt = stmt.where(GoldRate.metal == metal)
    if purity is not None:
        stmt = stmt.where(GoldRate.purity == purity)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/current", response_model=GoldRateRead, dependencies=[read])
async def current_rate(
    db: DbSession,
    currency: Currency = Query(default=Currency.PKR),
    metal: Metal = Query(default=Metal.gold),
    purity: int = Query(default=24, ge=1, le=24),
) -> GoldRate:
    """The rate in force today for (currency, metal, purity). 404 if none set.

    A rate keyed in advance for a future date is deliberately not "current" —
    see `app.services.gold_rate.rate_in_force`.
    """
    rate = await rate_in_force(db, currency=currency, purity=purity, metal=metal)
    if rate is None:
        quoted = f"{purity}k" if metal is Metal.gold else "999"
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No {metal.value} rate set yet for {currency.value} at {quoted}.",
        )
    return rate


@router.post("", response_model=GoldRateRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_rate(
    payload: GoldRateCreate, db: DbSession, current: CurrentUser
) -> GoldRate:
    """
    Set the rate the shop prices at.

    Audited, because this is the number every invoice, every costing and every
    metal valuation reads. A rate keyed wrong and corrected an hour later
    leaves a trail of bills priced off it, and "who set 9,999 and when" has to
    be answerable.
    """
    rate = GoldRate(**payload.model_dump())
    db.add(rate)
    await db.flush()
    await log_action(
        db,
        user=current,
        action="gold_rate.create",
        resource_type="gold_rate",
        resource_id=rate.id,
        after=snapshot(rate),
    )
    await db.commit()
    await db.refresh(rate)
    return rate


@router.delete("/{rate_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[write])
async def delete_rate(rate_id: int, db: DbSession, current: CurrentUser) -> None:
    """
    Remove a rate. The whole row goes into the log first — after this there is
    nothing left to compare against, and a deleted rate is exactly the record
    somebody will want to see later.
    """
    rate = await db.get(GoldRate, rate_id)
    if rate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gold rate not found")
    await log_action(
        db,
        user=current,
        action="gold_rate.delete",
        resource_type="gold_rate",
        resource_id=rate_id,
        before=snapshot(rate),
    )
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


# ---------------------------------------------------------------------------
# Live market rates — display only
# ---------------------------------------------------------------------------
LIVE_CAVEAT = (
    "International spot converted to this currency, not the local market rate. "
    "The bazaar sets its own, differing by the import premium and the day's dollar. "
    "Nothing on this page prices anything — invoices and costing use the rate you set."
)


@router.get("/live", response_model=LiveMetalRates, dependencies=[read])
async def live_rates(
    currency: Currency = Query(default=Currency.PKR),
    refresh: bool = Query(
        default=False, description="Bypass the short cache and call the feed again."
    ),
) -> LiveMetalRates:
    """
    What the market is doing, on its own tab and nowhere else.

    This endpoint touches no database and posts nothing. It exists so the shop
    can glance at spot beside the rate it has set, and the two are deliberately
    never the same field: a feed that priced invoices would reprice the counter
    mid-sale from a figure nobody in the shop agreed to.

    Never 5xx. Every failure — no key, feed down, rate-limited, nonsense body —
    comes back as a 200 carrying `unavailable`, because a display panel that
    takes the page down with it when a third party has a bad morning is worse
    than one that says it does not know.
    """
    rates = await metal_feed.fetch(currency.value, force=refresh)
    return LiveMetalRates(
        currency=currency,
        gold_per_gram=rates.gold_per_gram,
        silver_per_gram=rates.silver_per_gram,
        fetched_at=rates.fetched_at,
        unavailable=rates.unavailable,
        caveat=LIVE_CAVEAT,
        source="goldpricez.com",
    )
