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

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.currency import Currency
from app.models.gold_rate import GoldRate


async def rate_in_force(
    db: AsyncSession,
    *,
    currency: Currency = Currency.PKR,
    purity: int = 24,
    as_of: date | None = None,
) -> GoldRate | None:
    """
    The latest rate for (currency, purity) that is effective on `as_of`.

    A rate dated ahead of `as_of` is a plan, not a price, and is ignored. Ties
    on the same date fall to the highest id, so the last rate keyed that day
    wins — which is what the shop means when it updates the rate at noon.
    """
    effective = as_of or datetime.now(timezone.utc).date()
    stmt = (
        select(GoldRate)
        .where(
            GoldRate.currency == currency,
            GoldRate.purity == purity,
            GoldRate.rate_date <= effective,
        )
        .order_by(desc(GoldRate.rate_date), desc(GoldRate.id))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
