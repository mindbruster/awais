"""
Resolving "the rate in force".

Five call sites used to spell this query out themselves — invoices, product
costing, the routing engine, the ledger's opening balances and the rates
endpoint — and all five shared the same flaw: they took the newest row by
`rate_date` with no bound against today, so a rate keyed in advance for
tomorrow's opening silently priced everything happening now.

Rates are entered several times a day and forward-dated deliberately, so this
is not hypothetical. One resolver, one rule: the most recent rate that has
actually taken effect.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.currency import Currency
from app.models.gold_rate import GoldRate
from app.models.metal import Metal


async def rate_in_force(
    db: AsyncSession,
    *,
    currency: Currency = Currency.PKR,
    purity: int = 24,
    metal: Metal = Metal.gold,
    as_of: date | None = None,
) -> GoldRate | None:
    """
    The latest rate for (currency, metal, purity) effective on `as_of`.

    A rate dated ahead of `as_of` is a plan, not a price, and is ignored. Ties
    on the same date fall to the highest id, so the last rate keyed that day
    wins — which is what the shop means when it updates the rate at noon.

    Purity narrows gold only. Silver is quoted out of a thousand and its karat
    column carries nothing, so matching on it would find no row at all — the
    metal alone identifies a silver rate, and `fineness_pct` on the row says
    what purity it was quoted at.
    """
    effective = as_of or clock.today()
    stmt = (
        select(GoldRate)
        .where(
            GoldRate.currency == currency,
            GoldRate.metal == metal,
            GoldRate.rate_date <= effective,
        )
        .order_by(desc(GoldRate.rate_date), desc(GoldRate.id))
        .limit(1)
    )
    if metal is Metal.gold:
        stmt = stmt.where(GoldRate.purity == purity)
    return (await db.execute(stmt)).scalar_one_or_none()


def fine_rate_per_g(rate: GoldRate) -> Decimal:
    """
    Rupees per gram of *pure* metal, from a rate quoted at a trade purity.

    The ledger holds metal in fine grams and values it per fine gram; the shop
    quotes what it quotes — 24k gold, 999 silver. For 24k those are the same
    number, which is why nothing needed this while the system only knew gold.
    They are not the same for silver: Rs 340 a gram of 999 is Rs 340.34 a gram
    of pure, and across a few kilos that gap is real money sitting between the
    stock report and the trial balance.
    """
    per_g = Decimal(str(rate.rate_per_g or 0))
    if rate.fineness_pct:
        factor = Decimal(str(rate.fineness_pct)) / Decimal("100")
    elif rate.metal is Metal.gold and rate.purity:
        factor = Decimal(str(rate.purity)) / Decimal("24")
    else:
        factor = Decimal("1")
    if factor <= 0:
        return per_g
    return (per_g / factor).quantize(Decimal("0.0001"))
