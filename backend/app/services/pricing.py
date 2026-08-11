from decimal import Decimal

# Ratti are the traditional subdivision the counter negotiates in: a discount is
# offered as "6 ratti off", not as a percentage. 96 ratti is the customary base
# but it is not universal, so it travels on the line rather than being baked in.
DEFAULT_RATTI_BASE = 96


def d(v) -> Decimal:
    return Decimal(str(v or 0))


def apply_ratti_discount(
    gold_weight_g: Decimal,
    discount_ratti: Decimal,
    ratti_base: int = DEFAULT_RATTI_BASE,
) -> Decimal:
    """
    Reduce billable gold weight by a discount quoted in ratti.

        billable = weight / base * (base - discount)

    So on a 96 base, 6 ratti bills 90/96 of the weight and 10 ratti bills 86/96.
    It is a proportional reduction, not a flat subtraction — the customer is
    being charged for less gold than the piece contains, which is how this trade
    discounts without touching the rate.

    Kept whole (not rounded to the gram) so the reduction survives into the
    money calculation; rounding here would lose paisas on every line.
    """
    base = Decimal(str(ratti_base or DEFAULT_RATTI_BASE))
    if base <= 0:
        return d(gold_weight_g)
    remaining = base - d(discount_ratti)
    if remaining <= 0:
        # A discount at or beyond the whole base means the gold is free. Clamp
        # rather than invert — negative billable weight would credit the
        # customer for metal they are receiving.
        return Decimal("0")
    return (d(gold_weight_g) / base * remaining).quantize(Decimal("0.0001"))


def price_line(
    *,
    gold_weight_g: Decimal,
    gold_purity: int | None,
    gold_rate_per_g: Decimal,
    stone_weight_ct: Decimal,
    stone_rate_per_ct: Decimal,
    labor_amount: Decimal,
    line_discount: Decimal = Decimal("0"),
    discount_ratti: Decimal = Decimal("0"),
    ratti_base: int = DEFAULT_RATTI_BASE,
    quantity: int = 1,
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Returns (gold_amount, stone_amount, line_total).

    Gold is reduced by any ratti discount first, then purity-adjusted:
    billable = weight / base * (base - ratti), effective = billable * purity/24.
    The two are separate levers — the ratti discount is what the shop gives
    away, the purity factor is what the metal actually is — and applying the
    discount before the purity factor keeps "6 ratti off" meaning the same
    proportion whatever karat the piece is.

    **Weights and labour on a line are per unit**, and every component is
    multiplied by `quantity`. This has to match the rest of the system: issuing
    an invoice deducts `product weight x quantity` from stock and the profit
    report costs `product cost x quantity`. Pricing one unit while shipping and
    costing N means a multi-unit line is sold at a fraction of its price — the
    shop gives away the extra pieces and the books still look right.

    line_total = (gold + stone + labor) x quantity - line_discount, floored at 0.
    `line_discount` is a whole-line figure, not per unit: it is a rupee amount
    the counter knocked off this line, not a per-piece rate.
    """
    qty = Decimal(str(max(int(quantity or 1), 0)))
    billable_g = apply_ratti_discount(gold_weight_g, discount_ratti, ratti_base)
    purity_factor = d(gold_purity) / Decimal("24") if gold_purity else Decimal("1")
    gold_amount = (billable_g * purity_factor * d(gold_rate_per_g) * qty).quantize(Decimal("0.01"))
    stone_amount = (d(stone_weight_ct) * d(stone_rate_per_ct) * qty).quantize(Decimal("0.01"))
    labor_total = (d(labor_amount) * qty).quantize(Decimal("0.01"))
    raw_total = gold_amount + stone_amount + labor_total - d(line_discount)
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
