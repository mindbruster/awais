"""
What a piece's stones actually cost.

Stock is reported as one running figure per grade because that is the question
the counter asks — "how much 12 PTR do I have". Cost is a different question
with a different answer: the 120 carats on the shelf are fifty bought in
January at Rs 8,000 and seventy bought in March at Rs 9,200, and a piece made
from the January parcel cost Rs 8,000 a carat however much later stone sits
beside it.

Averaging the two is the alternative, and it hides exactly what is worth
seeing. A parcel bought dear vanishes into the mean, every piece afterwards
looks equally profitable, and the buying mistake never appears on any report.
So issues draw oldest parcel first and each draw remembers the rate it came
out at.

Everything here works in landed rupees per carat: the parcel's rate, converted
at the exchange rate on the bill, loaded with that bill's freight and
certification percentage. All three are snapshotted onto the draw, because all
three are editable and a piece's cost must not move when somebody corrects a
freight figure two months later.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.purchase import StonePurchase, StonePurchaseItem
from app.models.stone import Stone
from app.models.stone_draw import StoneDraw

_CT = Decimal("0.0001")
_RATE = Decimal("0.0001")


def d(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


def landed_rate_per_ct(item: StonePurchaseItem, purchase: StonePurchase | None) -> Decimal:
    """
    What one carat of this parcel actually cost, in rupees.

    Three things sit between the number on the bill and the number that belongs
    in a piece's cost: the bill may be in dollars, the supplier may load freight
    and certification as a percentage on top, and both are recorded separately
    from the line rate. A costing that used the bare rate would understate every
    imported parcel by the whole of both.
    """
    rate = d(item.rate_per_ct) * d(item.fx_rate_to_pkr)
    extra = d(purchase.extra_cost_pct) if purchase is not None else Decimal("0")
    return (rate * (Decimal("1") + extra / Decimal("100"))).quantize(_RATE)


@dataclass
class Allocation:
    """One parcel's contribution to an issue."""

    purchase_item_id: int | None
    weight_ct: Decimal
    rate_per_ct_pkr: Decimal


async def _remaining_by_parcel(db: AsyncSession, stone_id: int) -> list[tuple[StonePurchaseItem, StonePurchase | None, Decimal]]:
    """
    Every parcel of this stone with carats still undrawn, oldest first.

    Ordered by when the stone was *bought*, not by when the row was written:
    a bill keyed late still consumed its parcel in the order the shop actually
    received it, and ordering by id would let a back-dated entry jump the queue.
    """
    parcels = (
        await db.execute(
            select(StonePurchaseItem, StonePurchase)
            .join(StonePurchase, StonePurchase.id == StonePurchaseItem.purchase_id)
            .where(StonePurchaseItem.stone_id == stone_id)
            .order_by(StonePurchase.purchased_at, StonePurchaseItem.id)
        )
    ).all()
    if not parcels:
        return []

    drawn = dict(
        (
            await db.execute(
                select(StoneDraw.purchase_item_id, func.coalesce(func.sum(StoneDraw.weight_ct), 0))
                .where(
                    StoneDraw.purchase_item_id.in_([item.id for item, _ in parcels])
                )
                .group_by(StoneDraw.purchase_item_id)
            )
        ).all()
    )

    out = []
    for item, purchase in parcels:
        remaining = (d(item.weight_ct) - d(drawn.get(item.id, 0))).quantize(_CT)
        if remaining > 0:
            out.append((item, purchase, remaining))
    return out


async def allocate(db: AsyncSession, *, stone: Stone, carats: Decimal) -> list[Allocation]:
    """
    Spread an issue across parcels, oldest first.

    Falls off the end deliberately. A shop's opening stone stock predates this
    system, and so does every parcel bought before it was installed — there are
    real carats on the shelf with no purchase line behind them. Refusing to
    issue those would mean the shop cannot use its own stones until somebody
    keys in years of history, so whatever the parcels cannot cover is allocated
    against no parcel at all and costed at the stone master's rate. It is
    recorded rather than dropped, so a stock report can show how much of what
    went out had no purchase behind it.
    """
    wanted = d(carats).quantize(_CT)
    if wanted <= 0:
        return []

    allocations: list[Allocation] = []
    for item, purchase, remaining in await _remaining_by_parcel(db, stone.id):
        if wanted <= 0:
            break
        take = min(remaining, wanted)
        allocations.append(
            Allocation(
                purchase_item_id=item.id,
                weight_ct=take,
                rate_per_ct_pkr=landed_rate_per_ct(item, purchase),
            )
        )
        wanted = (wanted - take).quantize(_CT)

    if wanted > 0:
        allocations.append(
            Allocation(
                purchase_item_id=None,
                weight_ct=wanted,
                rate_per_ct_pkr=d(stone.default_rate_per_ct),
            )
        )
    return allocations


def weighted_rate(draws: list[StoneDraw]) -> Decimal:
    """
    One rupees-per-carat figure for a set of draws.

    The leg line carries a single rate because that is what the product costing
    multiplies by. When an issue spans two parcels the honest single number is
    the weighted mean of what was actually drawn — not the newest rate, not the
    master's, and not the unweighted average of the two, which would price a
    twenty-carat draw and a one-carat draw the same.
    """
    total_ct = sum((d(x.weight_ct) for x in draws), Decimal("0"))
    if total_ct <= 0:
        return Decimal("0")
    value = sum((d(x.weight_ct) * d(x.rate_per_ct_pkr) for x in draws), Decimal("0"))
    return (value / total_ct).quantize(_RATE)


async def release(db: AsyncSession, *, leg_stone_id: int, carats: Decimal) -> None:
    """
    Put undrawn carats back, newest draw first.

    Stones handed back unset return to the parcel they came out of, and the
    order matters: releasing oldest-first would restore the January parcel
    while the March carats stayed consumed, so the next issue would draw
    January again and the shop would work through its stock in an order it
    never physically used.

    Newest-first is the exact reverse of how they were taken, which leaves the
    parcels as though the returned carats had never left.
    """
    back = d(carats).quantize(_CT)
    if back <= 0:
        return
    draws = (
        (
            await db.execute(
                select(StoneDraw)
                .where(StoneDraw.leg_stone_id == leg_stone_id)
                .order_by(StoneDraw.id.desc())
            )
        )
        .scalars()
        .all()
    )
    for draw in draws:
        if back <= 0:
            break
        held = d(draw.weight_ct)
        give = min(held, back)
        remaining = (held - give).quantize(_CT)
        if remaining > 0:
            draw.weight_ct = remaining
        else:
            await db.delete(draw)
        back = (back - give).quantize(_CT)
