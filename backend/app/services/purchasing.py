"""
The buying side: metal back over the counter, and stones from suppliers.

Everything a purchase has to get right lives here rather than in the router,
because both halves of a purchase have to agree and there is exactly one place
that can guarantee it. Stock moves through `inventory.post_movement`, the books
move through `ledger.post_entry` — never a journal row written by hand — and a
purchase that posts one without the other is the failure this module exists to
make impossible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import SystemAccount
from app.models.design import JobLeg, LegStatus, LegStone
from app.models.inventory import InventoryItem, InventoryType
from app.models.journal import Commodity, JournalEntry, PartyType
from app.models.purchase import OldGoldPurchase, StonePurchase, StonePurchaseItem
from app.models.stock_movement import MovementType
from app.models.stone import Stone, StoneCategory
from app.services.inventory import post_movement
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry, reverse_entry

# Entries and movements a purchase makes are found again by these, which is how
# a reversal knows what it is undoing.
OLD_GOLD_SOURCE = "old_gold_purchase"
STONE_PURCHASE_SOURCE = "stone_purchase"

_PKR = Decimal("0.01")
_CT = Decimal("0.0001")

# Advisory-lock keys, in the same 7_3xx_xxx block the rest of the app uses so
# nothing here can collide with a serial mint or the opening-balance run.
_OLD_GOLD_NO_LOCK = 7_300_010
_STONE_PURCHASE_NO_LOCK = 7_300_011
_RAW_STONE_ITEM_LOCK = 7_300_012
# Melt pots are per purity, so the lock is too — buying 22k must not serialise
# against someone buying 21k at the next counter.
_RAW_GOLD_ITEM_LOCK_BASE = 7_420_000


# --------------------------------------------------------------------------
# Document numbers
# --------------------------------------------------------------------------
async def _next_no(db: AsyncSession, *, model, column, prefix: str, lock_key: int) -> str:
    """
    `<prefix>-<YY>-<NNNNN>`, serialised on an advisory lock.

    The next value comes from the highest suffix in use, never from a row
    count: delete OG-26-00003 out of five and a count-based mint hands out
    OG-26-00005 again, which the unique index then rejects.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_key))
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(func.coalesce(func.max(cast(func.substring(column, r"(\d+)$"), Integer)), 0))
            .select_from(model)
            .where(column.like(f"{prefix}-{year}-%"))
        )
    ).scalar_one()
    return f"{prefix}-{year}-{int(highest) + 1:05d}"


async def next_old_gold_no(db: AsyncSession) -> str:
    return await _next_no(
        db,
        model=OldGoldPurchase,
        column=OldGoldPurchase.purchase_no,
        prefix="OG",
        lock_key=_OLD_GOLD_NO_LOCK,
    )


async def next_stone_purchase_no(db: AsyncSession) -> str:
    return await _next_no(
        db,
        model=StonePurchase,
        column=StonePurchase.purchase_no,
        prefix="SP",
        lock_key=_STONE_PURCHASE_NO_LOCK,
    )


# --------------------------------------------------------------------------
# Where bought material lands in stock
# --------------------------------------------------------------------------
async def raw_gold_item(db: AsyncSession, *, purity: int) -> InventoryItem:
    """
    The melt pot for one purity, created on first use.

    Keyed on purity rather than on a per-purchase row because that is what the
    bucket means physically: 22k bought this morning is the same metal as the
    22k already in the safe. A row per purchase would leave the shop with a
    hundred stock lines it can never reconcile against one weighing.

    Get-or-create is a read followed by a write, so it is serialised — two
    counters buying 22k in the same second must not each mint their own pot.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_RAW_GOLD_ITEM_LOCK_BASE + purity)
    )
    item = (
        (
            await db.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.type == InventoryType.raw_gold,
                    InventoryItem.purity == purity,
                )
                .order_by(InventoryItem.id)
                .limit(1)
            )
        )
        .unique()
        .scalars()
        .first()
    )
    if item is None:
        item = InventoryItem(
            type=InventoryType.raw_gold,
            label=f"Raw gold {purity}k",
            purity=purity,
            quantity=0,
            weight_g=Decimal("0"),
            weight_ct=Decimal("0"),
        )
        db.add(item)
        await db.flush()
    return item


def grade_label(
    quality: str | None, cut: str | None, color: str | None, clarity: str | None
) -> str:
    parts = [p.strip() for p in (quality, cut, color, clarity) if p and p.strip()]
    return " / ".join(parts) if parts else "ungraded"


async def raw_stone_item(
    db: AsyncSession,
    *,
    stone: Stone,
    quality: str | None,
    cut: str | None,
    color: str | None,
    clarity: str | None,
) -> InventoryItem:
    """
    The packet a graded lot goes into, created on first use.

    Keyed on a derived label because `inventory_items` carries no stone
    reference and the schema is fixed. The label is built here rather than
    typed so the same grade bought twice lands in one packet instead of two the
    shop then has to reconcile by eye — "12 PTR · Commercial / Round / VS1" is
    one thing however many bills it arrived on.
    """
    label = f"{stone.name} · {grade_label(quality, cut, color, clarity)}"[:150]
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_RAW_STONE_ITEM_LOCK)
    )
    item = (
        (
            await db.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.type == InventoryType.raw_stone,
                    InventoryItem.label == label,
                )
                .order_by(InventoryItem.id)
                .limit(1)
            )
        )
        .unique()
        .scalars()
        .first()
    )
    if item is None:
        item = InventoryItem(
            type=InventoryType.raw_stone,
            label=label,
            quantity=0,
            weight_g=Decimal("0"),
            weight_ct=Decimal("0"),
        )
        db.add(item)
        await db.flush()
    return item


# --------------------------------------------------------------------------
# Old gold
# --------------------------------------------------------------------------
def old_gold_amount(weight_g: Decimal, rate_per_g: Decimal) -> Decimal:
    """What leaves the till: the weight as handed over, at the agreed rate."""
    return (d(weight_g) * d(rate_per_g)).quantize(_PKR)


def effective_fine_rate(amount: Decimal, fine_g: Decimal) -> Decimal:
    """
    What the shop paid per 24k-equivalent gram.

    The ticket rate is quoted against the weight as it came over the counter;
    the ledger holds fine grams. Valuing the fine quantity at the ticket rate
    would price 20g of 22k as 18.3333 × ticket and leave the entry short of the
    cash that actually went out. This is also the only number that can honestly
    be compared with the day's rate, which is itself per fine gram.
    """
    if d(fine_g) <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This purchase works out to no fine gold, so there is nothing to book.",
        )
    # Deliberately not rounded to the ledger's 4dp rate precision. `post_entry`
    # values the line off the rate handed to it and only rounds the copy it
    # stores, so keeping the full quotient here is what makes the gold line
    # come out at exactly the cash paid on a kilo as well as on a gram.
    return (d(amount) / d(fine_g)).quantize(Decimal("0.00000001"))


async def post_old_gold_purchase(
    db: AsyncSession,
    purchase: OldGoldPurchase,
    *,
    seller: str,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Metal in at what it cost, cash out at what was paid.

    Debit 1130 Gold in Hand for the fine grams, credit 1110 Cash in Hand for
    the rupees. Nothing values this at the market rate: the shop bought below
    it, and booking the metal in at market would recognise the whole spread as
    profit before the piece has been sold or even melted.

    The seller's name is handed in rather than read off `purchase.customer`, so
    this can post against a row that was only just flushed without tripping a
    lazy load on an async session.
    """
    fine = fine_grams(purchase.weight_g, purchase.purity)
    amount = d(purchase.amount)
    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A purchase of zero rupees has nothing to post."
        )
    rate = effective_fine_rate(amount, fine)

    who = seller
    draft = EntryDraft(
        memo=(
            f"{purchase.purchase_no}: bought {d(purchase.weight_g)}g "
            f"{purchase.kind.value} gold from {who} at {d(purchase.rate_per_g)}/g"
        ),
        entry_date=purchase.purchased_at.date(),
        source_type=OLD_GOLD_SOURCE,
        source_id=purchase.id,
    )
    draft.add(
        Posting(
            account_code=SystemAccount.GOLD_IN_HAND.value,
            quantity=fine,
            commodity=Commodity.GOLD,
            rate=rate,
            native_weight_g=d(purchase.weight_g),
            native_purity=purchase.purity,
            memo=f"{fine}g fine at {rate}/g",
        )
    )
    # No party tag on the cash line. The party fields say *whose balance this
    # line is part of*, and cash in hand is the shop's own — tagging it with the
    # seller would put a customer's name on money that is not owed to or by
    # them. Who sold the metal is on the purchase row, and in the memo.
    draft.add(
        Posting(
            account_code=SystemAccount.CASH_IN_HAND.value,
            quantity=-amount,
            memo=f"Paid to {who}",
        )
    )
    return await post_entry(db, draft, user_id=user_id)


async def reverse_old_gold_purchase(
    db: AsyncSession, purchase: OldGoldPurchase, *, user_id: int | None = None
) -> JournalEntry:
    """
    Undo both halves, or neither.

    The books go first because `reverse_entry` is what refuses a second attempt
    — doing the stock first would let a double-click hand the metal back twice
    before the ledger objected. If the gold has since been issued to a worker,
    `post_movement` refuses and the whole transaction rolls back, which is the
    right answer: you cannot un-buy metal that is no longer there.
    """
    if purchase.journal_entry_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{purchase.purchase_no} never posted to the ledger, so there is nothing to reverse.",
        )
    original = await db.get(JournalEntry, purchase.journal_entry_id)
    if original is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The journal entry behind {purchase.purchase_no} is missing.",
        )
    reversal = await reverse_entry(
        db, original, memo=f"Reversal of old gold purchase {purchase.purchase_no}", user_id=user_id
    )

    if purchase.inventory_item_id is not None:
        item = await db.get(InventoryItem, purchase.inventory_item_id)
        if item is not None:
            await post_movement(
                db,
                item=item,
                type=MovementType.adjustment,
                weight_g_delta=-d(purchase.weight_g),
                reference_type=OLD_GOLD_SOURCE,
                reference_id=purchase.id,
                notes=f"Reversal of {purchase.purchase_no}",
                user_id=user_id,
            )
    return reversal


# --------------------------------------------------------------------------
# Stone purchases
# --------------------------------------------------------------------------
def stone_line_amount(weight_ct: Decimal, rate_per_ct: Decimal) -> Decimal:
    return (d(weight_ct) * d(rate_per_ct)).quantize(_PKR)


def apply_extra_cost(subtotal: Decimal, extra_cost_pct: Decimal) -> Decimal:
    """
    The loading the supplier quotes on top of the goods.

    Applied to the subtotal, not per line, because that is how the bill is
    written — and because splitting it across lines would invent a per-carat
    cost the supplier never quoted.
    """
    return (d(subtotal) * (Decimal("1") + d(extra_cost_pct) / Decimal("100"))).quantize(_PKR)


async def post_stone_purchase(
    db: AsyncSession,
    purchase: StonePurchase,
    *,
    supplier_name: str,
    line_count: int,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Debit 1140 Stone Inventory, credit 2110 Suppliers against this supplier.

    The full total goes to inventory, loading included: freight and
    certification are part of what the stones cost, and expensing them would
    understate stock and overstate this month's costs at the same time.
    """
    total = d(purchase.total)
    if total <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A bill of zero rupees has nothing to post."
        )
    who = supplier_name
    draft = EntryDraft(
        memo=f"{purchase.purchase_no}: stones from {who}"
        + (f" ({purchase.reference})" if purchase.reference else ""),
        entry_date=purchase.purchased_at.date(),
        source_type=STONE_PURCHASE_SOURCE,
        source_id=purchase.id,
    )
    draft.add(
        Posting(
            account_code=SystemAccount.STONE_INVENTORY.value,
            quantity=total,
            memo=f"{line_count} lot(s) on {purchase.purchase_no}",
        )
    )
    draft.add(
        Posting(
            account_code=SystemAccount.SUPPLIERS.value,
            quantity=-total,
            party_type=PartyType.supplier,
            party_id=purchase.supplier_id,
            memo=f"Payable to {who}",
        )
    )
    return await post_entry(db, draft, user_id=user_id)


# --------------------------------------------------------------------------
# Stone stock
# --------------------------------------------------------------------------
@dataclass
class StoneStockLine:
    """One grade of one stone: what came in, what went into pieces, what's left."""

    stone_id: int
    stone_name: str = ""
    stone_kind: object = None
    category: object = None
    abbreviation: str | None = None
    quality: str | None = None
    cut: str | None = None
    color: str | None = None
    clarity: str | None = None
    purchased_quantity: int = 0
    purchased_weight_ct: Decimal = field(default_factory=lambda: Decimal("0"))
    purchased_value: Decimal = field(default_factory=lambda: Decimal("0"))
    used_quantity: int = 0
    used_weight_ct: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def available_quantity(self) -> int:
        return self.purchased_quantity - self.used_quantity

    @property
    def available_weight_ct(self) -> Decimal:
        return (self.purchased_weight_ct - self.used_weight_ct).quantize(_CT)

    @property
    def avg_rate_per_ct(self) -> Decimal:
        if self.purchased_weight_ct <= 0:
            return Decimal("0")
        return (self.purchased_value / self.purchased_weight_ct).quantize(_CT)


async def stone_stock(
    db: AsyncSession,
    *,
    category: StoneCategory | None = None,
    stone_id: int | None = None,
    quality: str | None = None,
    cut: str | None = None,
    clarity: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[StoneStockLine]:
    """
    Purchased, used and available per stone *and grade*.

    The grade is part of the key, not a decoration. "How much 12 PTR do I have"
    is not a question a shop asks — it asks how much 12 PTR *commercial* it has,
    and answering at stone level would net a deluxe lot against a commercial one
    and report metal it cannot sell as if it were interchangeable.

    Purchases carry their own grading snapshot and fall back to the stone
    master's when a line left it blank; consumption has only the stone it was
    issued against, so it reads the master. That is what makes the two sides
    line up: a lot bought as the master describes it is the same key as the same
    lot going into a piece.

    Consumption is issued minus returned, in both count and weight, because a
    setter returning nine of ten stones and one returning the same carats in
    chips are different events and only the first leaves stones on the shelf.

    A date window narrows both sides equally, so the report reads as movement
    for the period; leave it off for the position as it stands today. Available
    can come out negative, and that is information: it means stones went into
    pieces that this system never saw bought.
    """
    # Snapshot first, master second — the bill is the record of what arrived.
    p_quality = func.coalesce(StonePurchaseItem.quality, Stone.quality)
    p_cut = func.coalesce(StonePurchaseItem.cut, Stone.cut)
    p_color = func.coalesce(StonePurchaseItem.color, Stone.color)
    p_clarity = func.coalesce(StonePurchaseItem.clarity, Stone.clarity)

    bought = (
        select(
            StonePurchaseItem.stone_id,
            p_quality.label("quality"),
            p_cut.label("cut"),
            p_color.label("color"),
            p_clarity.label("clarity"),
            func.coalesce(func.sum(StonePurchaseItem.quantity), 0),
            func.coalesce(func.sum(StonePurchaseItem.weight_ct), 0),
            func.coalesce(func.sum(StonePurchaseItem.amount), 0),
        )
        .join(StonePurchase, StonePurchase.id == StonePurchaseItem.purchase_id)
        .join(Stone, Stone.id == StonePurchaseItem.stone_id)
        .group_by(StonePurchaseItem.stone_id, p_quality, p_cut, p_color, p_clarity)
    )
    used = (
        select(
            LegStone.stone_id,
            Stone.quality,
            Stone.cut,
            Stone.color,
            Stone.clarity,
            func.coalesce(
                func.sum(LegStone.quantity_issued - LegStone.quantity_returned), 0
            ),
            func.coalesce(
                func.sum(LegStone.weight_issued_ct - LegStone.weight_returned_ct), 0
            ),
        )
        .join(Stone, Stone.id == LegStone.stone_id)
        .join(JobLeg, JobLeg.id == LegStone.leg_id)
        # A cancelled leg consumed nothing. Its stones either came back to the
        # shelf on cancellation — where they were already credited as a stock
        # movement, so counting them here would deduct the same carats twice —
        # or are still outstanding against the worker, which is a debt to chase
        # and not a stone that went into a piece. Either way, treating a
        # cancelled leg as consumption understates what is available to set.
        .where(JobLeg.status != LegStatus.cancelled)
        .group_by(LegStone.stone_id, Stone.quality, Stone.cut, Stone.color, Stone.clarity)
    )

    if category is not None:
        bought = bought.where(Stone.category == category)
        used = used.where(Stone.category == category)
    if stone_id is not None:
        bought = bought.where(StonePurchaseItem.stone_id == stone_id)
        used = used.where(LegStone.stone_id == stone_id)
    if quality:
        bought = bought.where(p_quality.ilike(f"%{quality}%"))
        used = used.where(Stone.quality.ilike(f"%{quality}%"))
    if cut:
        bought = bought.where(p_cut.ilike(f"%{cut}%"))
        used = used.where(Stone.cut.ilike(f"%{cut}%"))
    if clarity:
        bought = bought.where(p_clarity.ilike(f"%{clarity}%"))
        used = used.where(Stone.clarity.ilike(f"%{clarity}%"))
    if date_from is not None:
        bought = bought.where(func.date(StonePurchase.purchased_at) >= date_from)
        used = used.where(func.date(JobLeg.issued_at) >= date_from)
    if date_to is not None:
        bought = bought.where(func.date(StonePurchase.purchased_at) <= date_to)
        used = used.where(func.date(JobLeg.issued_at) <= date_to)

    lines: dict[tuple, StoneStockLine] = {}

    def _line(key: tuple) -> StoneStockLine:
        if key not in lines:
            lines[key] = StoneStockLine(
                stone_id=key[0], quality=key[1], cut=key[2], color=key[3], clarity=key[4]
            )
        return lines[key]

    for sid, q, c, col, cl, qty, wt, val in (await db.execute(bought)).all():
        line = _line((sid, q, c, col, cl))
        line.purchased_quantity += int(qty or 0)
        line.purchased_weight_ct += d(wt)
        line.purchased_value += d(val)

    for sid, q, c, col, cl, qty, wt in (await db.execute(used)).all():
        line = _line((sid, q, c, col, cl))
        line.used_quantity += int(qty or 0)
        line.used_weight_ct += d(wt)

    if not lines:
        return []

    stones = {
        s.id: s
        for s in (
            (
                await db.execute(
                    select(Stone).where(Stone.id.in_({k[0] for k in lines}))
                )
            )
            .unique()
            .scalars()
            .all()
        )
    }
    for key, line in lines.items():
        stone = stones.get(key[0])
        if stone is None:
            continue
        line.stone_name = stone.name
        line.stone_kind = stone.kind
        line.category = stone.category
        line.abbreviation = stone.abbreviation
        line.purchased_weight_ct = line.purchased_weight_ct.quantize(_CT)
        line.used_weight_ct = line.used_weight_ct.quantize(_CT)
        line.purchased_value = line.purchased_value.quantize(_PKR)

    return sorted(
        (ln for ln in lines.values() if ln.stone_name),
        key=lambda ln: (ln.stone_name.lower(), grade_label(ln.quality, ln.cut, ln.color, ln.clarity)),
    )
