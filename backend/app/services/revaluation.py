"""
Bringing metal on the books up to what it is worth this morning.

The shop's capital is mostly gold, and gold held at what it cost is not gold
held at what it is worth. Between the two sits the whole reason a jeweller
watches the rate: a shop can trade flat for a month and be materially richer,
or trade well and be poorer, and a balance sheet at historic cost says neither.

**Posted, not merely reported** — the shop's choice, and the consequences are
real: the balance sheet shows metal at market, and profit includes the rate
movement. A falling rate then books a loss in a month the floor may have worked
well. That is true, and it is the price of the balance sheet being true.

How it works with this ledger, which holds metal in fine grams and money in
`value_pkr` on the same line: a revaluation posts **only money**. The gram
balance of 1130 is untouched — no metal moved, and pretending otherwise would
corrupt the one figure the safe can be counted against. What changes is the
rupee value sitting beside those grams. `balance(commodity=GOLD)` therefore
still returns exactly what it did, and `balance_pkr` returns the revalued
figure, which is precisely the split those two functions already exist to make.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.account import SystemAccount
from app.models.currency import Currency
from app.models.journal import Commodity, JournalEntry
from app.models.metal import Metal
from app.services import ledger
from app.services.gold_rate import fine_rate_per_g, rate_in_force
from app.services.ledger import EntryDraft, Posting, d, post_entry

SOURCE_TYPE = "metal_revaluation"

_PKR = Decimal("0.01")
_G = Decimal("0.0001")

# Which account holds each metal, and in which commodity its grams are counted.
_HELD = {
    Metal.gold: (SystemAccount.GOLD_IN_HAND, Commodity.GOLD),
    Metal.silver: (SystemAccount.SILVER_IN_HAND, Commodity.SILVER),
}


@dataclass
class MetalValuation:
    metal: Metal
    fine_grams: Decimal
    rate_per_fine_g: Decimal | None
    book_value: Decimal
    market_value: Decimal | None
    # Positive is a gain the books have not yet recognised.
    difference: Decimal | None
    # Why this metal could not be valued, when it could not be.
    unpriced: str | None = None


async def value(db: AsyncSession, *, as_of: date | None = None) -> list[MetalValuation]:
    """
    What each metal is on the books at, and what it is worth today.

    Read-only, and safe to call as often as the screen refreshes. Nothing here
    posts; `post` below is the deliberate second step, because moving a balance
    sheet to market is a decision somebody makes rather than something that
    happens while a page loads.
    """
    when = as_of or clock.today()
    out: list[MetalValuation] = []
    for metal, (account, commodity) in _HELD.items():
        fine = (
            await ledger.balance(db, account_code=account.value, commodity=commodity)
        ).quantize(_G)
        book = (await ledger.balance_pkr(db, account_code=account.value)).quantize(_PKR)
        rate_row = await rate_in_force(db, currency=Currency.PKR, purity=24, metal=metal, as_of=when)
        if rate_row is None:
            out.append(
                MetalValuation(
                    metal=metal,
                    fine_grams=fine,
                    rate_per_fine_g=None,
                    book_value=book,
                    market_value=None,
                    difference=None,
                    unpriced=(
                        f"No {metal.value} rate is on record for {when}, so what the shop "
                        "is holding cannot be valued."
                    ),
                )
            )
            continue
        rate = fine_rate_per_g(rate_row)
        market = (fine * rate).quantize(_PKR)
        out.append(
            MetalValuation(
                metal=metal,
                fine_grams=fine,
                rate_per_fine_g=rate,
                book_value=book,
                market_value=market,
                difference=(market - book).quantize(_PKR),
            )
        )
    return out


async def post(
    db: AsyncSession,
    *,
    as_of: date | None = None,
    user_id: int | None = None,
) -> tuple[JournalEntry | None, list[MetalValuation]]:
    """
    Move the metal accounts to market, and book the difference.

    One entry covering both metals, because it is one event — the market moved
    — and splitting it would put two half-explanations in the journal where the
    shop remembers one decision.

    Metal that cannot be valued is skipped rather than revalued to zero, which
    would write off the entire holding as a "loss". A metal already at market
    contributes nothing and is simply left alone.

    Returns `None` for the entry when nothing needed moving. That is a real
    outcome on a quiet day and must not read as a failure.
    """
    when = as_of or clock.today()
    valuations = await value(db, as_of=when)

    draft = EntryDraft(
        memo=f"Metal revalued to the market of {when}",
        entry_date=when,
        source_type=SOURCE_TYPE,
    )
    total = Decimal("0")
    for v in valuations:
        if v.difference is None or v.difference == 0:
            continue
        account, _ = _HELD[v.metal]
        # A money-only line on a metal account. The grams are deliberately
        # untouched: no metal moved, and altering the gram balance would break
        # the one figure that can be checked against the safe.
        draft.add(
            Posting(
                account_code=account.value,
                quantity=v.difference,
                memo=(
                    f"{v.fine_grams}g fine at {v.rate_per_fine_g}/g "
                    f"= {v.market_value}, held at {v.book_value}"
                ),
            )
        )
        total += v.difference

    if total == 0:
        return None, valuations

    draft.add(
        Posting(
            account_code=SystemAccount.METAL_REVALUATION.value,
            quantity=-total,
            memo="Unrealised movement on metal held",
        )
    )
    return await post_entry(db, draft, user_id=user_id), valuations
