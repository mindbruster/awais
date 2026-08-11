"""
Where the money actually came from.

"Profit = revenue − cost" is true and almost useless to a jeweller. The shop
pulls four separate levers and they behave completely differently: the spread
between the rate metal was costed at and the rate it sold at, the wastage
charged on top of the weight delivered, the making charge, and the margin on
stones. Against them sit the giveaways — the ratti discount, the flat discount
and the round-off.

Two shops with identical profit can be running in opposite directions: one
earning on making charges with the metal flat, another making nothing on labour
and living entirely on a rate spread that will close the moment the market
turns. A single profit number cannot tell them apart, and the owner cannot fix
what he cannot see.

The decomposition is exact by construction: every component is derived from the
same figures the invoice was priced from, and whatever does not reconcile is
reported as `unattributed` rather than quietly absorbed. A residual that starts
growing means a line was priced from something this function does not know
about, which is worth finding out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceItem
from app.models.product import Product
from app.services.pricing import (
    DEFAULT_RATTI_BASE,
    apply_ratti_discount,
    apply_sale_wastage,
)

_PKR = Decimal("0.01")
_ZERO = Decimal("0")


def d(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


@dataclass
class MarginBreakdown:
    """One period's profit, split by the lever that produced it."""

    revenue: Decimal = _ZERO
    cost_of_goods: Decimal = _ZERO
    gross_profit: Decimal = _ZERO

    # --- what earned it ---
    # Metal sold at a higher rate than it was costed at. Market movement plus
    # whatever spread the shop bought at. Falls to nothing in a flat market,
    # which is exactly why it must be visible separately.
    rate_spread: Decimal = _ZERO
    # Billing for more grams than the piece contains. Pure margin, and the lever
    # most likely to be cut first when a customer pushes back.
    wastage_charged: Decimal = _ZERO
    # Labour billed to the customer, before what the workers were paid.
    making_charges: Decimal = _ZERO
    # Stones billed less what they cost.
    stone_margin: Decimal = _ZERO

    # --- what gave it away ---
    # Each is held positive and subtracted, so the report reads as "we earned X
    # and handed back Y" rather than as a signed number nobody can scan.
    ratti_discount: Decimal = _ZERO
    cash_discount: Decimal = _ZERO
    round_off: Decimal = _ZERO
    # What the workers were paid to make the pieces sold in this period.
    making_cost: Decimal = _ZERO

    # Metal billed that has no matching recorded cost — a piece made before the
    # shop had a gold rate, one that never went through the stock form, or a
    # line billing a different weight from the piece it points at. It reads as
    # profit because nothing was ever booked against it, which is worth saying
    # out loud rather than burying in a residual: it is not margin the shop
    # earned, it is bookkeeping it has not done.
    uncosted_metal: Decimal = _ZERO

    # gross_profit minus everything above. Should sit at zero; anything else is
    # a line priced from something this decomposition does not model.
    unattributed: Decimal = _ZERO

    lines: int = 0
    invoices: int = 0
    notes: list[str] = field(default_factory=list)


def line_components(
    item: InvoiceItem,
    invoice: Invoice,
    product: Product | None,
) -> dict[str, Decimal]:
    """
    Pull one invoice line apart into the levers that produced its price.

    Re-derives the weights the same way `price_line` did — net, then marked up
    by wastage, then reduced by the ratti discount — because the stored
    `gold_amount` is the end of that chain and the middle steps are where the
    margin story is.
    """
    qty = Decimal(str(item.quantity or 1))
    net_g = d(item.gold_weight_g)
    charged_g = apply_sale_wastage(
        net_g, d(item.sale_wastage_pct), d(item.sale_wastage_g)
    )
    billable_g = apply_ratti_discount(
        charged_g, d(item.discount_ratti), int(item.ratti_base or DEFAULT_RATTI_BASE)
    )

    purity_factor = (
        d(item.gold_purity) / Decimal("24") if item.gold_purity else Decimal("1")
    )
    sale_rate = (
        d(item.gold_rate_per_g)
        if item.gold_rate_per_g and d(item.gold_rate_per_g) > 0
        else d(invoice.gold_rate_per_g)
    )

    # The rate the metal was capitalised at when the piece was stocked. Without
    # a stocked product there is nothing to compare against, so the whole gold
    # amount is reported as spread-free and the cost side carries it instead.
    cost_rate = d(product.gold_rate_at_cost) if product and product.gold_rate_at_cost else sale_rate

    def value(grams: Decimal, rate: Decimal) -> Decimal:
        return (grams * purity_factor * rate * qty).quantize(_PKR)

    # Metal the customer actually receives, valued at both rates. The gap is
    # the spread.
    net_at_sale = value(net_g, sale_rate)
    net_at_cost = value(net_g, cost_rate)

    return {
        "rate_spread": (net_at_sale - net_at_cost).quantize(_PKR),
        # Grams billed beyond what the piece holds.
        "wastage_charged": value(charged_g - net_g, sale_rate),
        # Grams given back. Positive; subtracted by the caller.
        "ratti_discount": value(charged_g - billable_g, sale_rate),
        "making_charges": (d(item.labor_amount) * qty).quantize(_PKR),
        "stone_revenue": d(item.stone_amount),
        "cash_discount": d(item.line_discount),
        "net_at_cost": net_at_cost,
    }


def product_costs(product: Product | None, quantity: int) -> tuple[Decimal, Decimal, Decimal]:
    """
    (gold cost, stone cost, making cost) for the units sold on a line.

    `material_cost` is gold plus stones as one figure, so the gold half is
    recomputed from the locked rate and the stones are what remains. Doing it
    this way rather than storing three columns means the split can never
    disagree with the total it came from.
    """
    if product is None:
        return _ZERO, _ZERO, _ZERO
    qty = Decimal(str(quantity or 1))
    purity_factor = (
        d(product.gold_purity) / Decimal("24") if product.gold_purity else Decimal("1")
    )
    gold_cost = (
        d(product.gold_weight_g) * purity_factor * d(product.gold_rate_at_cost) * qty
    ).quantize(_PKR)
    stone_cost = (d(product.material_cost) * qty - gold_cost).quantize(_PKR)
    making_cost = (d(product.total_cost) * qty).quantize(_PKR)
    return gold_cost, max(stone_cost, _ZERO), making_cost


def accumulate(
    breakdown: MarginBreakdown,
    *,
    item: InvoiceItem,
    invoice: Invoice,
    product: Product | None,
) -> None:
    """Fold one line into the running breakdown."""
    parts = line_components(item, invoice, product)
    gold_cost, stone_cost, making_cost = product_costs(product, item.quantity or 1)

    # The base value of the metal sold, less what it was actually costed at.
    # Zero for a properly stocked piece billed at its own weight — the two are
    # the same number. Non-zero means the cost side is missing or disagrees,
    # and that gap is revenue no lever can explain.
    breakdown.uncosted_metal += (parts["net_at_cost"] - gold_cost).quantize(_PKR)
    breakdown.rate_spread += parts["rate_spread"]
    breakdown.wastage_charged += parts["wastage_charged"]
    breakdown.making_charges += parts["making_charges"]
    breakdown.stone_margin += (parts["stone_revenue"] - stone_cost).quantize(_PKR)
    breakdown.ratti_discount += parts["ratti_discount"]
    breakdown.cash_discount += parts["cash_discount"]
    breakdown.making_cost += making_cost
    breakdown.cost_of_goods += (gold_cost + stone_cost + making_cost).quantize(_PKR)
    breakdown.lines += 1


def finalise(breakdown: MarginBreakdown) -> MarginBreakdown:
    """
    Close the books on a breakdown: gross profit, and whatever failed to
    reconcile.

    The residual is reported rather than distributed. Spreading it across the
    levers would make the report look tidy while quietly moving money between
    the numbers the owner is about to make decisions on.
    """
    breakdown.gross_profit = (breakdown.revenue - breakdown.cost_of_goods).quantize(_PKR)
    attributed = (
        breakdown.rate_spread
        + breakdown.wastage_charged
        + breakdown.making_charges
        + breakdown.stone_margin
        + breakdown.uncosted_metal
        - breakdown.ratti_discount
        - breakdown.cash_discount
        - breakdown.round_off
        - breakdown.making_cost
    ).quantize(_PKR)
    breakdown.unattributed = (breakdown.gross_profit - attributed).quantize(_PKR)

    # Each component is quantized to paisas independently, so a line can drift
    # by a couple of them and a hundred-line month by a rupee. Report the figure
    # always — it is the honest number — but only raise it as a finding when it
    # is bigger than rounding can explain, or the note cries wolf every month
    # and stops being read.
    rounding_slack = (Decimal("0.05") * Decimal(max(breakdown.lines, 1))).quantize(_PKR)
    if abs(breakdown.unattributed) > rounding_slack:
        breakdown.notes.append(
            f"{breakdown.unattributed} could not be attributed to a lever — more than "
            f"rounding across {breakdown.lines} lines explains. The usual cause is a line "
            "billing a different weight from the piece it is linked to, or a sale of stock "
            "that never went through the stock form and so has no costed rate."
        )
    if breakdown.uncosted_metal != _ZERO:
        breakdown.notes.append(
            f"{breakdown.uncosted_metal} of the profit above is metal with no matching "
            "recorded cost — pieces made before the shop had a gold rate, sold without going "
            "through the stock form, or billed at a different weight from the piece they are "
            "linked to. It is not margin that was earned."
        )
    if breakdown.rate_spread < _ZERO:
        breakdown.notes.append(
            "The rate spread is negative: metal sold below what it was costed at. That is "
            "either a falling market or stock bought too dear, and it is worth knowing which."
        )
    return breakdown
