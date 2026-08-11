"""
Compute and persist `products.material_cost`.

material_cost = gold value at completion time (purity-adjusted, in PKR by
default, priced at the rate locked on `products.gold_rate_at_cost`) + sum over
product_stones of (qty × weight_ct × rate_per_ct).

We use PKR as the canonical cost currency because the gold rate master is
typically maintained in PKR. Stones snapshot their own currency at attach time
but the per-product material_cost is summed without FX conversion — fine for a
single-shop deployment, would need normalisation for multi-currency books.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.currency import Currency
from app.models.gold_rate import GoldRate
from app.models.product import Product
from app.models.product_stone import ProductStone
from app.services.gold_rate import rate_in_force


async def _current_gold_rate_pkr(db: AsyncSession) -> Decimal:
    rate = await rate_in_force(db, currency=Currency.PKR, purity=24)
    return Decimal(str(rate.rate_per_g)) if rate else Decimal("0")


async def recompute_material_cost(
    db: AsyncSession, product: Product, *, gold_rate_pkr: Decimal | None = None
) -> Decimal:
    """
    Recompute material_cost for a product and write it back. Caller commits.

    The gold rate is locked on the first pass and reused on every later one, so
    that recomputing (which happens whenever a stone is attached or detached)
    only ever re-values the *stones*. Re-pricing the gold at whatever the rate
    happens to be that day would rewrite the product's historical cost, and
    with it every profit figure that references the product.

    Pass `gold_rate_pkr` to force a specific rate — it becomes the locked rate
    if none is set yet.
    """
    rate = (
        gold_rate_pkr
        if gold_rate_pkr is not None
        else (
            Decimal(str(product.gold_rate_at_cost))
            if product.gold_rate_at_cost is not None
            else await _current_gold_rate_pkr(db)
        )
    )
    # Only lock a rate that means something. Locking a zero — which is what
    # `_current_gold_rate_pkr` returns before the shop has entered its first
    # rate — freezes the piece at no cost *forever*, because every later pass
    # sees a non-NULL value and reuses it. The piece then shows infinite margin
    # on every report it appears in. Leaving it NULL lets the next recompute,
    # once a rate exists, lock a real one.
    if product.gold_rate_at_cost is None and rate > 0:
        product.gold_rate_at_cost = rate

    purity_factor = (
        Decimal(str(product.gold_purity)) / Decimal("24") if product.gold_purity else Decimal("1")
    )
    gold_value = (Decimal(str(product.gold_weight_g)) * purity_factor * rate).quantize(
        Decimal("0.01")
    )

    stones = (
        await db.execute(
            select(ProductStone).where(ProductStone.product_id == product.id)
        )
    ).scalars().all()
    stone_value = Decimal("0")
    for s in stones:
        stone_value += (
            Decimal(str(s.weight_ct)) * Decimal(str(s.rate_per_ct)) * Decimal(str(s.quantity))
        )
    stone_value = stone_value.quantize(Decimal("0.01"))

    total = (gold_value + stone_value).quantize(Decimal("0.01"))
    product.material_cost = total
    return total
