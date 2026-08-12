"""
Turning a foreign amount into rupees.

PKR is the book currency, so every posting has to reach a rupee value before it
can balance against anything else. This is the one place that conversion
happens, for the same reason `gold_rate.py` is the one place a gold rate is
resolved: five call sites each writing the query means five chances to forget
the date bound, and the bug is invisible — the books balance perfectly and are
wrong by the exchange rate.

Two rules, both learned from the gold rate:

* A rate keyed for a future date is a plan, not a price. `rate_in_force` will
  not use one.
* The rate used is snapshotted onto the journal line. A dollar invoice raised
  in March stays valued at March's rate; re-translating it as the rupee moves
  would rewrite last quarter's profit every time someone opened a report.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.currency import Currency
from app.models.exchange_rate import ExchangeRate

_PKR = Decimal("0.01")


def d(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


async def rate_in_force(
    db: AsyncSession, currency: Currency, *, as_of: date | None = None
) -> Decimal | None:
    """
    Rupees per one unit of `currency`, effective on `as_of`.

    Returns exactly 1 for PKR without touching the database — the base currency
    converts to itself, and storing a row for that would let someone enter a
    rate that isn't 1 and quietly revalue the entire book.
    """
    if currency is Currency.PKR:
        return Decimal("1")

    effective = as_of or datetime.now(timezone.utc).date()
    row = (
        await db.execute(
            select(ExchangeRate)
            .where(
                ExchangeRate.currency == currency,
                ExchangeRate.rate_date <= effective,
            )
            .order_by(desc(ExchangeRate.rate_date), desc(ExchangeRate.id))
            .limit(1)
        )
    ).scalar_one_or_none()
    return d(row.pkr_per_unit) if row and d(row.pkr_per_unit) > 0 else None


async def require_rate(
    db: AsyncSession, currency: Currency, *, as_of: date | None = None
) -> Decimal:
    """
    The rate, or a 409 explaining what to do about it.

    Refusing is deliberate, and it is the same call `routing.current_gold_rate`
    makes about an unvalued gram. Posting a dollar invoice at a guessed rate —
    or worse, at 1 — produces books that balance and are wrong by the whole
    exchange rate, with nothing to show anyone that it happened.
    """
    rate = await rate_in_force(db, currency, as_of=as_of)
    if rate is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No {currency.value} exchange rate is on record for that date, so this cannot "
            f"be valued in the books. Set today's {currency.value} rate under Gold rates → "
            "Exchange rates first.",
        )
    return rate


def to_pkr(amount: Decimal, rate: Decimal) -> Decimal:
    """Convert at a rate already resolved, so the caller has to have thought
    about which date's rate it is using."""
    return (d(amount) * d(rate)).quantize(_PKR)


async def snapshot_for_stone(db: AsyncSession, stone) -> tuple[Currency, Decimal]:
    """
    The currency a stone is priced in, and what converts it to rupees today.

    Called wherever a stone rate is written down — a product's breakdown, a
    setting leg, a supplier's bill. The pair is stored together on purpose: the
    rate alone is a number, and reading the currency back off the stone master
    later would let an edit to that master retroactively change what an old row
    meant.

    A stone master priced in a currency with no rate on record is refused
    rather than silently treated as rupees, which would understate the cost by
    the whole exchange rate and show the piece as far more profitable than it is.
    """
    currency = getattr(stone, "currency", None) or Currency.PKR
    return currency, await require_rate(db, currency)
