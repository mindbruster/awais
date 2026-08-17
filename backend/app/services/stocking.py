"""
Closing the manufacturing loop: a finished design becomes a sellable product.

A design accumulates legs and then stops. Everything the piece cost is sitting
in the legs — labour accrued per hop, metal issued and received, stones eaten
by the setter — and nothing turns that into a thing with a serial number that
the counter can sell. This is that step.

Three business decisions live here rather than in the router, for the same
reason routing.py holds its three: they have to give the same answer whoever
asks (the preview, the commit, a later import script), and a preview that
computes the cost differently from the commit is worse than no preview at all.

  * what the piece has cost so far — rolled up from the legs, never stored;
  * the weight arithmetic — gross, less stones, times purity;
  * the posting that moves the piece out of work-in-progress into stock.

Nothing here writes journal rows or inventory snapshots directly; `post_entry`
and `post_movement` own those.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from fastapi import HTTPException, status

from app.models.account import SystemAccount
from app.models.design import Design, DesignStatus, JobLeg, LegStatus
from app.models.journal import Commodity, JournalEntry
from app.models.product import Product
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry

# Entries this step posts are found again by this pair, the same way a leg's
# are — so a later correction can locate what stocking did.
SOURCE_TYPE = "design_stock"

_G = Decimal("0.0001")
_PKR = Decimal("0.01")

# A carat is a fifth of a gram, by definition. Stones are weighed in carats and
# the piece on a gram scale, so the two have to meet somewhere to get from what
# the scale says to the metal alone.
CARAT_G = Decimal("0.2")


# --------------------------------------------------------------------------
# What the piece has cost so far
# --------------------------------------------------------------------------
@dataclass
class StoneUse:
    """Stones that went into the piece and did not come back."""

    stone_id: int
    stone_name: str | None
    quantity_used: int
    weight_used_ct: Decimal
    rate_per_ct: Decimal

    @property
    def value(self) -> Decimal:
        return (self.weight_used_ct * self.rate_per_ct).quantize(_PKR)


@dataclass
class Hop:
    """One department's contribution to the piece, as the shop reads it."""

    leg_id: int
    sequence: int
    department: str
    worker: str | None
    status: LegStatus
    gold_in_g: Decimal
    gold_out_g: Decimal
    gold_purity: int | None
    piece_count: int
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    labour_basis: str
    labour_rate: Decimal
    labour_amount: Decimal
    stones: list[StoneUse] = field(default_factory=list)

    @property
    def stone_value(self) -> Decimal:
        return sum((s.value for s in self.stones), Decimal("0")).quantize(_PKR)


@dataclass
class Weights:
    """
    The weight arithmetic spelled out, because the counter has to be able to
    check it. `net_metal_g` is what gets priced and what the ledger moves;
    `pure_weight_g` is that in 24k-equivalent grams, which is the unit the
    ledger holds gold in.
    """

    gross_weight_g: Decimal
    stone_weight_ct: Decimal
    stone_weight_g: Decimal
    net_metal_g: Decimal
    gold_purity: int | None
    pure_weight_g: Decimal


@dataclass
class Rollup:
    """Everything the stock form needs, computed from the legs — never stored."""

    hops: list[Hop]
    stones: list[StoneUse]
    gold_issued_g: Decimal
    gold_received_g: Decimal
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    labour_total: Decimal
    stone_weight_ct: Decimal
    stone_value: Decimal
    pieces: int
    # The weight that came back from the last department to hand the piece over.
    # This is what the counter puts on the scale to check, not a sum: metal is
    # issued and received again at every hop, so totalling the receipts would
    # count the same piece once per department.
    last_received_g: Decimal
    last_purity: int | None


def live_legs(design: Design) -> list[JobLeg]:
    """
    The legs that still count.

    A cancelled leg's material and money were reversed out of the books, so
    including it here would charge the piece for work that was un-done — and
    the cost roll-up is what the product's total_cost is minted from.
    """
    return [leg for leg in design.legs if leg.status is not LegStatus.cancelled]


def open_leg(design: Design) -> JobLeg | None:
    return next((leg for leg in design.legs if leg.status is LegStatus.issued), None)


def ensure_stockable(design: Design) -> None:
    """
    Refuse to stock a piece that isn't finished, or one that already is.

    Both refusals are 409 rather than 400: the request is well-formed, it is
    the piece that is in the wrong state. Stocking twice would mint a second
    product for one physical piece and post its metal into Finished Goods
    again, so the design's own status is the guard and it is checked under a
    row lock at the call site.
    """
    if design.product_id is not None or design.status is DesignStatus.stocked:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{design.design_no} is already stocked"
            + (f" as product #{design.product_id}." if design.product_id else "."),
        )
    if design.status in (DesignStatus.sold, DesignStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{design.design_no} is {design.status.value} and cannot be stocked.",
        )
    # A lot is a dealing with a maker, not an article. Its metal becomes the
    # pieces it divides into, and each of those is stocked on its own — so
    # stocking the lot as well would post the same gold into Finished Goods
    # twice and mint a product for something that was never one piece.
    if design.is_lot:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{design.design_no} is a lot, not a piece."
            + (
                " It has been divided — stock the pieces individually."
                if design.status is DesignStatus.split
                else " Divide it into pieces first; those are what get stocked."
            ),
        )

    out = open_leg(design)
    if out is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{design.design_no} is still out with "
            f"{out.worker.name if out.worker else 'a worker'} at "
            f"{out.department.name}. Receive or cancel leg #{out.sequence} first — "
            "a piece that is not in the shop cannot be put into stock.",
        )
    if not any(leg.status is LegStatus.received for leg in design.legs):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Nothing has come back on {design.design_no} yet, so there is no piece "
            "to stock. Receive at least one leg first.",
        )


def roll_up(design: Design) -> Rollup:
    """
    Add the piece up from its legs.

    Deliberately derived on every read rather than cached on the design: the
    same rule the ledger balances follow. A stored roll-up would be a second
    place the cost lives, and the two would disagree the first time a leg was
    cancelled.
    """
    hops: list[Hop] = []
    totals = {
        "gold_issued_g": Decimal("0"),
        "gold_received_g": Decimal("0"),
        "wastage_allowed_g": Decimal("0"),
        "wastage_actual_g": Decimal("0"),
        "wastage_excess_g": Decimal("0"),
        "labour_total": Decimal("0"),
    }
    pieces = 0
    # Keyed by (stone, rate) rather than by stone alone. The same stone set on
    # two legs at two different rates is two different costs, and merging them
    # would force a blended rate the shop never agreed to.
    used: dict[tuple[int, Decimal], StoneUse] = {}

    for leg in live_legs(design):
        lines: list[StoneUse] = []
        for s in leg.stones:
            # What was set into the piece, not what failed to come back.
            # Stones the setter broke or owes are gone from stock too, but they
            # are his affair, not the article's cost — charging them here would
            # inflate what the shop believes the piece cost to make and would
            # bill the same carats twice, once to the piece and once to him.
            qty = s.quantity_used
            ct = d(s.weight_used_ct).quantize(_G)
            if ct <= 0 and qty <= 0:
                continue
            rate = d(s.rate_per_ct)
            lines.append(
                StoneUse(
                    stone_id=s.stone_id,
                    stone_name=s.stone.name if s.stone else None,
                    quantity_used=qty,
                    weight_used_ct=ct,
                    rate_per_ct=rate,
                )
            )
            key = (s.stone_id, rate)
            agg = used.get(key)
            if agg is None:
                used[key] = StoneUse(
                    stone_id=s.stone_id,
                    stone_name=s.stone.name if s.stone else None,
                    quantity_used=qty,
                    weight_used_ct=ct,
                    rate_per_ct=rate,
                )
            else:
                agg.quantity_used += qty
                agg.weight_used_ct = (agg.weight_used_ct + ct).quantize(_G)

        hops.append(
            Hop(
                leg_id=leg.id,
                sequence=leg.sequence,
                department=leg.department.name if leg.department else "—",
                worker=leg.worker.name if leg.worker else None,
                status=leg.status,
                gold_in_g=d(leg.gold_issued_g),
                gold_out_g=d(leg.gold_received_g),
                gold_purity=leg.gold_issued_purity,
                piece_count=leg.piece_count,
                wastage_allowed_g=d(leg.wastage_allowed_g),
                wastage_actual_g=d(leg.wastage_actual_g),
                wastage_excess_g=d(leg.wastage_excess_g),
                labour_basis=leg.labour_basis.value,
                labour_rate=d(leg.labour_rate),
                labour_amount=d(leg.labour_amount),
                stones=lines,
            )
        )
        pieces += leg.piece_count
        totals["gold_issued_g"] += d(leg.gold_issued_g)
        totals["gold_received_g"] += d(leg.gold_received_g)
        totals["wastage_allowed_g"] += d(leg.wastage_allowed_g)
        totals["wastage_actual_g"] += d(leg.wastage_actual_g)
        totals["wastage_excess_g"] += d(leg.wastage_excess_g)
        totals["labour_total"] += d(leg.labour_amount)

    closed = [leg for leg in design.legs if leg.status is LegStatus.received]
    last = max(closed, key=lambda leg: leg.sequence, default=None)
    stones = sorted(used.values(), key=lambda s: (s.stone_id, s.rate_per_ct))

    return Rollup(
        hops=hops,
        stones=stones,
        gold_issued_g=totals["gold_issued_g"].quantize(_G),
        gold_received_g=totals["gold_received_g"].quantize(_G),
        wastage_allowed_g=totals["wastage_allowed_g"].quantize(_G),
        wastage_actual_g=totals["wastage_actual_g"].quantize(_G),
        wastage_excess_g=totals["wastage_excess_g"].quantize(_G),
        labour_total=totals["labour_total"].quantize(_PKR),
        stone_weight_ct=sum((s.weight_used_ct for s in stones), Decimal("0")).quantize(_G),
        stone_value=sum((s.value for s in stones), Decimal("0")).quantize(_PKR),
        pieces=pieces,
        last_received_g=d(last.gold_received_g).quantize(_G) if last else Decimal("0"),
        last_purity=last.gold_issued_purity if last else None,
    )


# --------------------------------------------------------------------------
# The weight arithmetic
# --------------------------------------------------------------------------
def stone_grams(weight_ct: Decimal) -> Decimal:
    return (d(weight_ct) * CARAT_G).quantize(_G)


def derive_weights(
    *,
    gross_weight_g: Decimal,
    stone_weight_ct: Decimal,
    gold_purity: int | None,
    net_metal_g: Decimal | None = None,
) -> Weights:
    """
    gross − stones = net metal; net × purity/24 = pure.

    The counter weighs the finished piece whole, stones and all, but the shop
    only owns metal by weight — so the stones have to come off before anything
    is priced. `net_metal_g` lets the counter state the metal directly (he may
    have weighed it before setting); when he does, it is checked against the
    gross rather than trusted, because a net heavier than the piece it came out
    of would capitalise gold that is not there.

    Pure grams come from `ledger.fine_grams`, not a second conversion written
    here: the figure this returns is the one that gets posted, and two
    implementations of "×purity/24" would drift apart at the fourth decimal.
    """
    stones_g = stone_grams(stone_weight_ct)
    gross = d(gross_weight_g).quantize(_G)
    implied = (gross - stones_g).quantize(_G)
    net = d(net_metal_g).quantize(_G) if net_metal_g is not None else implied

    if net <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The metal in this piece works out at {net}g. {gross}g gross less "
            f"{stone_weight_ct}ct of stones ({stones_g}g) leaves nothing to stock — "
            "check the gross weight and the stone lines.",
        )
    if net > implied:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{net}g of metal cannot come out of a {gross}g piece carrying "
            f"{stone_weight_ct}ct of stones ({stones_g}g). At most {implied}g is metal.",
        )

    return Weights(
        gross_weight_g=gross,
        stone_weight_ct=d(stone_weight_ct).quantize(_G),
        stone_weight_g=stones_g,
        net_metal_g=net,
        gold_purity=gold_purity,
        pure_weight_g=fine_grams(net, gold_purity),
    )


def capitalised_gold_value(
    net_metal_g: Decimal, gold_purity: int | None, rate: Decimal
) -> Decimal:
    """
    The gold half of `products.material_cost`, as the costing service stores it.

    Mirrored here so the preview quotes the figure the commit will actually
    write. It is deliberately *not* `pure_weight_g x rate`: the ledger rounds
    the metal to a tenth of a milligram before valuing it and this does not, so
    at a five-figure rate per gram the two land a few rupees apart. Both are
    right for what they are — the ledger has to balance on the quantity it
    stored, the cost is the metal as weighed — and a preview that showed the
    ledger's figure would be quoting a cost the product never carries.
    """
    factor = d(gold_purity) / Decimal("24") if gold_purity else Decimal("1")
    return (d(net_metal_g) * factor * d(rate)).quantize(_PKR)


def total_cost(labour_total: Decimal, other_charges: Decimal) -> Decimal:
    """
    What making this piece cost in money.

    Material is deliberately not in here: `products.total_cost` is the making
    charge and `products.material_cost` is the capitalised gold and stones.
    Profit is revenue − (material + total_cost), and collapsing the two would
    make it impossible to say whether a thin margin came from the workshop or
    from the metal.
    """
    return (d(labour_total) + d(other_charges)).quantize(_PKR)


# --------------------------------------------------------------------------
# The posting
# --------------------------------------------------------------------------
async def post_stocking(
    db,
    *,
    design: Design,
    product: Product,
    weights: Weights,
    rate: Decimal,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Move the piece out of work-in-progress and into Finished Goods.

    While the piece is being made, every leg that comes back debits Gold in
    Hand — so the metal now embodied in a finished piece is sitting in 1130
    alongside the loose bullion in the safe, which is wrong the moment the
    piece is sellable: it is no longer metal the shop can issue to a worker.
    This entry says so. Debit 1150 Finished Goods, credit 1130 Gold in Hand,
    for the piece's fine grams valued at the same rate that is locked onto
    `products.gold_rate_at_cost` — one rate for the books and the costing, so
    neither can be re-priced against the other later.

    Stones are not on this entry. They never entered the ledger: leg issue
    moves stone *stock*, and there is no posting against 1140 to draw down, so
    crediting it here would invent a balance in order to spend it. Their value
    reaches the product through `material_cost`, which is where the sale reads
    cost from.

    The shape is copied from `routing.post_leg_receive` on purpose — signed
    fine grams, GOLD commodity, the as-weighed figure carried alongside on
    `native_weight_g` for the statement to show.
    """
    fine = weights.pure_weight_g
    native = weights.net_metal_g
    draft = EntryDraft(
        memo=f"{design.design_no}: stocked as {product.serial_no} — "
        f"{native}g{f' {weights.gold_purity}k' if weights.gold_purity else ''} into finished goods",
        source_type=SOURCE_TYPE,
        source_id=product.id,
    )
    draft.add(
        Posting(
            account_code=SystemAccount.FINISHED_GOODS.value,
            quantity=fine,
            commodity=Commodity.GOLD,
            rate=rate,
            native_weight_g=native,
            native_purity=weights.gold_purity,
            memo=f"{product.serial_no} — {product.name}",
        )
    )
    draft.add(
        Posting(
            account_code=SystemAccount.GOLD_IN_HAND.value,
            quantity=-fine,
            commodity=Commodity.GOLD,
            rate=rate,
            native_weight_g=-native,
            native_purity=weights.gold_purity,
            memo=f"Metal embodied in {design.design_no}",
        )
    )
    return await post_entry(db, draft, user_id=user_id)
