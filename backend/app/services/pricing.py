from decimal import Decimal


def d(v) -> Decimal:
    return Decimal(str(v or 0))


def price_line(
    *,
    gold_weight_g: Decimal,
    gold_purity: int | None,
    gold_rate_per_g: Decimal,
    stone_weight_ct: Decimal,
    stone_rate_per_ct: Decimal,
    labor_amount: Decimal,
    line_discount: Decimal = Decimal("0"),
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Returns (gold_amount, stone_amount, line_total).
    Gold is purity-adjusted: effective_weight = weight * purity/24 (only when purity given).
    line_total = gold + stone + labor - line_discount, clamped to >= 0.
    """
    purity_factor = d(gold_purity) / Decimal("24") if gold_purity else Decimal("1")
    gold_amount = (d(gold_weight_g) * purity_factor * d(gold_rate_per_g)).quantize(Decimal("0.01"))
    stone_amount = (d(stone_weight_ct) * d(stone_rate_per_ct)).quantize(Decimal("0.01"))
    raw_total = gold_amount + stone_amount + d(labor_amount) - d(line_discount)
    line_total = max(raw_total, Decimal("0")).quantize(Decimal("0.01"))
    return gold_amount, stone_amount, line_total


def invoice_totals(
    *,
    line_totals: list[Decimal],
    gold_rate_per_g: Decimal,
    discount_amount: Decimal,
    discount_weight_g: Decimal,
    tax_amount: Decimal,
) -> tuple[Decimal, Decimal]:
    """
    Returns (subtotal, total). Discount can be expressed as a flat amount AND/OR
    as a weight in grams (converted at gold_rate_per_g).
    """
    subtotal = sum((d(t) for t in line_totals), Decimal("0")).quantize(Decimal("0.01"))
    weight_discount = (d(discount_weight_g) * d(gold_rate_per_g)).quantize(Decimal("0.01"))
    total = (subtotal - d(discount_amount) - weight_discount + d(tax_amount)).quantize(
        Decimal("0.01")
    )
    if total < 0:
        total = Decimal("0.00")
    return subtotal, total
