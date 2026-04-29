"""
Compute and persist `products.material_cost`.

material_cost = gold value at completion time (purity-adjusted, in PKR by
default) + sum over product_stones of (qty × weight_ct × rate_per_ct).

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


async def _current_gold_rate_pkr(db: AsyncSession) -> Decimal:
    stmt = (
        select(GoldRate)
        .where(GoldRate.currency == Currency.PKR, GoldRate.purity == 24)
        .order_by(desc(GoldRate.rate_date), desc(GoldRate.id))
        .limit(1)
    )
    rate = (await db.execute(stmt)).scalar_one_or_none()
    return Decimal(str(rate.rate_per_g)) if rate else Decimal("0")


async def recompute_material_cost(
    db: AsyncSession, product: Product, *, gold_rate_pkr: Decimal | None = None
) -> Decimal:
    """
    Recompute material_cost for a product and write it back. Caller commits.
    Pass `gold_rate_pkr` to lock in a specific rate (e.g. snapshot at completion);
    otherwise the most recent PKR rate is used.
    """
    rate = gold_rate_pkr if gold_rate_pkr is not None else await _current_gold_rate_pkr(db)
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
