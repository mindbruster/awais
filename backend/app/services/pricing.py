from decimal import Decimal

# Ratti are the traditional subdivision the counter negotiates in: a discount is
# offered as "6 ratti off", not as a percentage. 96 ratti is the customary base
# but it is not universal, so it travels on the line rather than being baked in.
DEFAULT_RATTI_BASE = 96


def d(v) -> Decimal:
    return Decimal(str(v or 0))


def apply_sale_wastage(
    net_weight_g: Decimal,
    wastage_pct: Decimal = Decimal("0"),
    wastage_g: Decimal = Decimal("0"),
) -> Decimal:
    """
    Add the wastage the customer is charged for on top of the metal delivered.

        billable = net * (1 + pct/100) + flat

    This is revenue, not loss: the shop bills for more gold than the piece
    contains. It is the inverse of the ratti discount and both can appear on the
    same line — the counter marks up with wastage and gives back with ratti, and
    each has to stay visible separately or the margin report cannot say which
    lever moved.

    Percentage and flat grams are additive rather than exclusive so a quote like
    "10% plus half a gram" survives; either alone is the common case.
    """
    base = d(net_weight_g)
    return (base * (Decimal("1") + d(wastage_pct) / Decimal("100")) + d(wastage_g)).quantize(
        Decimal("0.0001")
    )


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
    sale_wastage_pct: Decimal = Decimal("0"),
    sale_wastage_g: Decimal = Decimal("0"),
    quantity: int = 1,
    gold_tunch_pct: Decimal | None = None,
    gold_charged_in: str = "rupees",
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """
    Returns (gold_amount, stone_amount, line_total, fine_g).

    `gold_charged_in` decides whether the metal on this line is sold for money
    or handed over as metal, and it is the difference between the two kinds of
    bill this shop writes.

    At the counter it is `"rupees"`: the gold is priced, lands in `gold_amount`,
    and the customer settles the whole thing in one figure.

    With another jeweller it is `"grams"`: the metal is **not priced at all**.
    `gold_amount` comes back zero, `line_total` carries only the stones, the
    labour and the discount, and `fine_g` carries what the buyer must hand over
    in metal. The rate is deliberately absent from that side of the bill —
    between houses it is agreed on the day the gold actually moves, and a rate
    printed weeks earlier would be quoting a price nobody accepted.

    `fine_g` is returned in both modes because it is simply what the line is
    worth in 24k-equivalent grams, which the metal ledger wants either way.

    Gold is marked up by any sale wastage, reduced by any ratti discount, then
    purity-adjusted:
        charged  = net * (1 + wastage_pct/100) + wastage_g
        billable = charged / base * (base - ratti)
        effective = billable * purity/24
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
    # Mark up first, discount second. Wastage is what the shop adds to the metal
    # delivered; the ratti discount is what it then gives back off the asking
    # figure. Doing it the other way round would apply the wastage percentage to
    # an already-discounted weight and quietly shrink the discount the customer
    # was promised.
    charged_g = apply_sale_wastage(gold_weight_g, sale_wastage_pct, sale_wastage_g)
    billable_g = apply_ratti_discount(charged_g, discount_ratti, ratti_base)
    # Tunch wins over karat when the line carries one — 91.6 is a reading off a
    # scale, 22 is a band somebody rounded it into. Same precedence as
    # `ledger.fine_grams`, so the money side and the metal side of a bill can
    # never disagree about how pure the gold was.
    if gold_tunch_pct:
        purity_factor = d(gold_tunch_pct) / Decimal("100")
    elif gold_purity:
        purity_factor = d(gold_purity) / Decimal("24")
    else:
        purity_factor = Decimal("1")
    # Kept unrounded for the money path. Rounding the grams to four places and
    # *then* multiplying by the rate moves the line total by up to a rupee on a
    # normal piece — which would silently restate every invoice already issued.
    # The metal path rounds at the end, where it is the figure being reported.
    fine_raw = billable_g * purity_factor * qty
    fine_g = fine_raw.quantize(Decimal("0.0001"))

    stone_amount = (d(stone_weight_ct) * d(stone_rate_per_ct) * qty).quantize(Decimal("0.01"))
    labor_total = (d(labor_amount) * qty).quantize(Decimal("0.01"))

    if gold_charged_in == "grams":
        # The metal is settled in metal. Pricing it here would put a rupee
        # figure on the bill for gold the buyer is paying for in gold, and the
        # customer would owe for the same metal twice.
        gold_amount = Decimal("0.00")
    else:
        gold_amount = (fine_raw * d(gold_rate_per_g)).quantize(Decimal("0.01"))

    raw_total = gold_amount + stone_amount + labor_total - d(line_discount)
    line_total = max(raw_total, Decimal("0")).quantize(Decimal("0.01"))
    return gold_amount, stone_amount, line_total, fine_g


def invoice_totals(
    *,
    line_totals: list[Decimal],
    gold_rate_per_g: Decimal,
    discount_amount: Decimal,
    discount_weight_g: Decimal,
    tax_amount: Decimal,
    gold_charged_in: str = "rupees",
) -> tuple[Decimal, Decimal]:
    """
    Returns (subtotal, total). Discount can be expressed as a flat amount AND/OR
    as a weight in grams (converted at gold_rate_per_g).

    On a bill whose gold is charged in grams the weight discount is *not*
    converted to money here. Nothing on that bill prices metal, so turning a
    gram giveaway into a rupee deduction would take it off the cash the jeweller
    owes for stones and making — money that has nothing to do with the metal
    that was discounted. It comes off the metal instead, where the caller
    applies it.
    """
    subtotal = sum((d(t) for t in line_totals), Decimal("0")).quantize(Decimal("0.01"))
    weight_discount = (
        Decimal("0.00")
        if gold_charged_in == "grams"
        else (d(discount_weight_g) * d(gold_rate_per_g)).quantize(Decimal("0.01"))
    )
    total = (subtotal - d(discount_amount) - weight_discount + d(tax_amount)).quantize(
        Decimal("0.01")
    )
    if total < 0:
        total = Decimal("0.00")
    return subtotal, total
