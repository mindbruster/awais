"""
The buying side: bullion from a dealer, metal back over the counter, stones
from suppliers.

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

from app.core import clock
from app.core import lock_keys
from app.models.account import SystemAccount
from app.models.design import JobLeg, LegStatus, LegStone
from app.models.inventory import InventoryItem, InventoryType
from app.models.journal import Commodity, JournalEntry, PartyType
from app.models.purchase import (
    GoldPaymentMode,
    GoldPurchase,
    GoldPurchaseItem,
    OldGoldPurchase,
    StonePurchase,
    StonePurchaseItem,
)
from app.models.stock_movement import MovementType
from app.models.stone import Stone, StoneCategory
from app.services.inventory import post_movement
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry, reverse_entry

# Entries and movements a purchase makes are found again by these, which is how
# a reversal knows what it is undoing.
OLD_GOLD_SOURCE = "old_gold_purchase"
STONE_PURCHASE_SOURCE = "stone_purchase"
GOLD_PURCHASE_SOURCE = "gold_purchase"

_PKR = Decimal("0.01")
_ZERO_PKR = Decimal("0")
_CT = Decimal("0.0001")

# Advisory-lock keys, in the same 7_3xx_xxx block the rest of the app uses so
# nothing here can collide with a serial mint or the opening-balance run.
_OLD_GOLD_NO_LOCK = lock_keys.OLD_GOLD_PURCHASE_NO
_STONE_PURCHASE_NO_LOCK = lock_keys.STONE_PURCHASE_NO
_GOLD_PURCHASE_NO_LOCK = lock_keys.GOLD_PURCHASE_NO
_RAW_STONE_ITEM_LOCK = lock_keys.RAW_STONE_ITEM
# Melt pots are per purity, so the lock is too — buying 22k must not serialise
# against someone buying 21k at the next counter.
_RAW_GOLD_ITEM_LOCK_BASE = lock_keys.RAW_GOLD_ITEM_BASE


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


async def next_gold_purchase_no(db: AsyncSession) -> str:
    # `GP`, not `OG`: a dealer's bill and a counter buy-back are different
    # documents and the shop has to be able to tell them apart by number alone.
    return await _next_no(
        db,
        model=GoldPurchase,
        column=GoldPurchase.purchase_no,
        prefix="GP",
        lock_key=_GOLD_PURCHASE_NO_LOCK,
    )


# --------------------------------------------------------------------------
# Where bought material lands in stock
# --------------------------------------------------------------------------
async def raw_gold_item(db: AsyncSession, *, purity: int, branch_id: int) -> InventoryItem:
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
                    # Per branch: 22k in the Anarkali safe is not 22k in the
                    # Gulberg safe, and topping one up from the other's counter
                    # would make both branch stock reports wrong at once.
                    InventoryItem.branch_id == branch_id,
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
            branch_id=branch_id,
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
    branch_id: int,
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
                    InventoryItem.branch_id == branch_id,
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
            branch_id=branch_id,
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
        entry_date=clock.shop_date(purchase.purchased_at),
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
# Gold purchases (from a dealer)
# --------------------------------------------------------------------------
def gold_line_amount(weight_g: Decimal, rate_per_g: Decimal) -> Decimal:
    """
    Quoted against the actual weight, not the fine weight.

    That is how the trade quotes it, and it matches how a buy-back is recorded,
    so the two documents can be compared without one of them being converted
    first. Fine grams are derived once, at posting time, from the purity.
    """
    return (d(weight_g) * d(rate_per_g)).quantize(_PKR)


async def lots_of(db: AsyncSession, purchase: GoldPurchase) -> list[GoldPurchaseItem]:
    """The bill's lots, fetched rather than read off the relationship."""
    return list(
        (
            await db.execute(
                select(GoldPurchaseItem)
                .where(GoldPurchaseItem.purchase_id == purchase.id)
                .order_by(GoldPurchaseItem.id)
            )
        )
        .scalars()
        .all()
    )


_CREDIT_ACCOUNT = {
    GoldPaymentMode.cash: SystemAccount.CASH_IN_HAND,
    GoldPaymentMode.bank: SystemAccount.BANK,
    GoldPaymentMode.credit: SystemAccount.SUPPLIERS,
}


async def post_gold_purchase(
    db: AsyncSession,
    purchase: GoldPurchase,
    items: list[GoldPurchaseItem],
    *,
    supplier_name: str,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Metal in at what it cost; money out of wherever it came from.

    Debit 1130 Gold in Hand once per lot, in *fine* grams, carrying that lot's
    own actual weight and purity — one aggregate posting would lose the purity
    breakdown the metal ledger reads, and a bill with 22k and 24k bars on it
    would become an untraceable blended figure.

    Carriage and assay are capitalised into the metal rather than expensed:
    they are part of what the gold cost, and expensing them would understate
    stock and overstate this month's costs at the same time. They are spread
    across the lots in proportion to value, which is why the rate per fine gram
    is derived from the loaded total rather than from what the dealer quoted.

    The credit side follows how it was paid. Only `credit` tags the supplier —
    the party fields say *whose balance this line is part of*, and cash out of
    the shop's own till is not the dealer's balance, however it got to them.
    """
    total = d(purchase.total)
    if total <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A bill of zero rupees has nothing to post."
        )
    subtotal = d(purchase.subtotal)
    if subtotal <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A bill with no metal on it has nothing to post."
        )

    draft = EntryDraft(
        memo=f"{purchase.purchase_no}: raw gold from {supplier_name}"
        + (f" ({purchase.reference})" if purchase.reference else ""),
        entry_date=clock.shop_date(purchase.purchased_at),
        source_type=GOLD_PURCHASE_SOURCE,
        source_id=purchase.id,
    )

    # Loading is apportioned by value, and the last lot absorbs the rounding —
    # otherwise the debits and the credit differ by a paisa and the entry will
    # not balance.
    booked = _ZERO_PKR
    for index, item in enumerate(items):
        amount = d(item.amount)
        if index == len(items) - 1:
            loaded = total - booked
        else:
            loaded = (total * amount / subtotal).quantize(_PKR)
        booked += loaded

        fine = fine_grams(item.weight_g, item.purity)
        if fine <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Lot {index + 1} weighs nothing, so there is no metal to book.",
            )
        draft.add(
            Posting(
                account_code=SystemAccount.GOLD_IN_HAND.value,
                quantity=fine,
                commodity=Commodity.GOLD,
                rate=effective_fine_rate(loaded, fine),
                native_weight_g=d(item.weight_g),
                native_purity=item.purity,
                memo=f"{d(item.weight_g)}g {item.purity}k = {fine}g fine",
            )
        )

    account = _CREDIT_ACCOUNT[purchase.payment_mode]
    on_credit = purchase.payment_mode is GoldPaymentMode.credit
    draft.add(
        Posting(
            account_code=account.value,
            quantity=-total,
            party_type=PartyType.supplier if on_credit else None,
            party_id=purchase.supplier_id if on_credit else None,
            memo=(
                f"Payable to {supplier_name}"
                if on_credit
                else f"Paid to {supplier_name} by {purchase.payment_mode.value}"
            ),
        )
    )
    return await post_entry(db, draft, user_id=user_id)


async def reverse_gold_purchase(
    db: AsyncSession, purchase: GoldPurchase, *, user_id: int | None = None
) -> JournalEntry:
    """
    Undo both halves, or neither.

    The books go first because `reverse_entry` is what refuses a second
    attempt — doing the stock first would let a double-click take the metal out
    twice before the ledger objected. If a bar has already been issued to a
    worker, `post_movement` refuses and the whole transaction rolls back, which
    is the right answer: you cannot un-buy metal that is no longer there.
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
        db,
        original,
        memo=f"Reversal of gold purchase {purchase.purchase_no}",
        user_id=user_id,
    )

    # Selected rather than read off `purchase.items`. The relationship is only
    # populated when the parent was loaded by a query that eager-loaded it;
    # rows added earlier in the same session leave it stale, and touching it
    # then triggers a lazy load, which async SQLAlchemy refuses outright.
    for item in await lots_of(db, purchase):
        if item.inventory_item_id is None:
            continue
        pot = await db.get(InventoryItem, item.inventory_item_id)
        if pot is None:
            continue
        await post_movement(
            db,
            item=pot,
            type=MovementType.adjustment,
            weight_g_delta=-d(item.weight_g),
            reference_type=GOLD_PURCHASE_SOURCE,
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
        entry_date=clock.shop_date(purchase.purchased_at),
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
