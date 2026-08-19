"""
Stock the shop already had on the day it started using this system.

The one legitimate way to put a quantity into a pot without a purchase behind
it — and it is still a document. It posts the material into its asset account
and the matching value into **3200 Opening Balance Equity**, which is what that
account is for: capital the owner brought in, in the form of metal rather than
cash.

Recorded once per pot. A second opening balance on the same pot is not an
opening balance, it is a correction, and corrections are counts — those carry a
reason and a second signature, which an opening balance does not.

Without this the only way to get go-live stock in was to type a weight onto the
row, which posted nothing. That is how the development database ended up with
1,195 fine grams of gold the ledger had never heard of.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.account import SystemAccount
from app.models.inventory import InventoryItem, InventoryType
from app.models.journal import Commodity, JournalEntry
from app.models.stock_movement import MovementType, StockMovement
from app.services.inventory import post_movement
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry

OPENING_STOCK_SOURCE = "opening_stock"

_G = Decimal("0.0001")
_PKR = Decimal("0.01")
_ZERO = Decimal("0")

# Where each kind of material lives, and in what unit the ledger carries it.
_ACCOUNTS: dict[InventoryType, tuple[SystemAccount, Commodity]] = {
    InventoryType.raw_gold: (SystemAccount.GOLD_IN_HAND, Commodity.GOLD),
    InventoryType.raw_silver: (SystemAccount.SILVER_IN_HAND, Commodity.SILVER),
    # Stones are carried in money, not carats: a parcel's value is what was
    # paid for it, and there is no rate to convert a grade into rupees.
    InventoryType.raw_stone: (SystemAccount.STONE_INVENTORY, Commodity.PKR),
    InventoryType.broken_stone: (SystemAccount.STONE_INVENTORY, Commodity.PKR),
    # A shop going live has made-up pieces on the shelf. They are carried in
    # money like the stones — a finished piece's value is what it cost to make,
    # not a rate anybody quotes.
    InventoryType.finished_product: (SystemAccount.FINISHED_GOODS, Commodity.PKR),
}


# The pot types a shop can declare an opening balance for, and which of those
# are weighed as metal. Derived from the account map rather than re-listed, so
# adding a type in one place cannot leave the go-live screen showing a pot the
# endpoint will refuse — or hiding one it would accept.
OPENABLE_TYPES: tuple[InventoryType, ...] = tuple(_ACCOUNTS)
METAL_TYPES: frozenset[InventoryType] = frozenset(
    t for t, (_acct, commodity) in _ACCOUNTS.items()
    if commodity in (Commodity.GOLD, Commodity.SILVER)
)


async def opened_item_ids(db: AsyncSession, item_ids: list[int]) -> set[int]:
    """
    Which of these pots already carry an opening balance.

    The set form of `already_opened`, for the screen that draws the whole
    checklist: one query for any number of pots instead of one each.
    """
    if not item_ids:
        return set()
    rows = await db.execute(
        select(StockMovement.inventory_item_id).where(
            StockMovement.inventory_item_id.in_(item_ids),
            StockMovement.reference_type == OPENING_STOCK_SOURCE,
        )
    )
    return set(rows.scalars().all())


async def already_opened(db: AsyncSession, item_id: int) -> bool:
    """Has this pot had its opening balance recorded already?"""
    return bool(
        (
            await db.execute(
                select(func.count(StockMovement.id)).where(
                    StockMovement.inventory_item_id == item_id,
                    StockMovement.reference_type == OPENING_STOCK_SOURCE,
                )
            )
        ).scalar_one()
    )


async def post_opening_stock(
    db: AsyncSession,
    item: InventoryItem,
    *,
    weight_g: Decimal,
    weight_ct: Decimal,
    quantity: int,
    rate_per_g: Decimal | None,
    value: Decimal | None,
    as_of: date | None = None,
    notes: str | None = None,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Put go-live stock into a pot, and the same value into the books.

    Refuses rather than guesses in three places, each of which would otherwise
    produce a balance sheet that looks right and is not:

    * **A pot that already has an opening balance.** Recording a second one
      doubles the shop's capital in a single click.
    * **Metal with no value.** Opening gold booked at nothing puts free metal on
      the balance sheet and understates the owner's capital by exactly its
      worth.
    * **Nothing to record.** A zero opening balance is not a fact worth an
      entry; it is a form somebody submitted empty.
    """
    if item.type not in _ACCOUNTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{item.type.value} has no opening-stock path — finished pieces arrive by "
            "being stocked off a job, not by being declared.",
        )
    if await already_opened(db, item.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{item.label} already has an opening balance. A second one would double "
            "the shop's capital — to correct what this pot holds, count it under "
            "Reconciliation.",
        )

    account, commodity = _ACCOUNTS[item.type]
    is_metal = commodity in (Commodity.GOLD, Commodity.SILVER)
    weight_g, weight_ct = d(weight_g), d(weight_ct)

    if is_metal and weight_g <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "An opening balance of no metal is not a balance."
        )
    if not is_metal and weight_ct <= 0 and quantity <= 0 and weight_g <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An opening balance of nothing is not a balance.",
        )

    if is_metal:
        fine = fine_grams(weight_g, item.purity, item.tunch_pct)
        if fine <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{item.label} has no purity on it, so this weight cannot be converted "
                "to fine grams. Set the pot's karat or tunch first.",
            )
        if value is not None and d(value) > 0:
            amount = d(value).quantize(_PKR)
            rate = (amount / fine).quantize(Decimal("0.00000001"))
        elif rate_per_g is not None and d(rate_per_g) > 0:
            rate = d(rate_per_g)
            amount = (fine * rate).quantize(_PKR)
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Say what this metal was worth when the books opened — a rate per fine "
                "gram, or the total value. Booked at nothing it would be free gold on "
                "the balance sheet and the owner's capital short by its worth.",
            )
        qty, native = fine, weight_g
    else:
        amount = d(value or 0).quantize(_PKR)
        if amount <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Say what this was worth when the books opened. Stones and finished "
                "pieces have no market rate to fall back on, so a value booked at "
                "nothing cannot be recovered later.",
            )
        rate = Decimal("1")
        qty, native = amount, None

    entry_date = as_of or clock.today()
    draft = EntryDraft(
        memo=f"Opening stock: {item.label}" + (f" — {notes}" if notes else ""),
        entry_date=entry_date,
        source_type=OPENING_STOCK_SOURCE,
        source_id=item.id,
    )
    draft.add(
        Posting(
            account_code=account.value,
            quantity=qty,
            commodity=commodity,
            rate=rate,
            native_weight_g=native,
            native_purity=item.purity if is_metal else None,
            memo=f"{item.label} on hand when the books opened",
        )
    )
    # The other side is capital, not income. The shop did not earn this metal
    # this year; it walked in with it, and booking it as income would overstate
    # the first period's profit by the whole opening stock.
    draft.add(
        Posting(
            account_code=SystemAccount.OPENING_BALANCE_EQUITY.value,
            quantity=-amount,
            memo=f"Opening stock brought in: {item.label}",
        )
    )
    entry = await post_entry(db, draft, user_id=user_id)

    await post_movement(
        db,
        item=item,
        type=MovementType.adjustment,
        quantity_delta=quantity or 0,
        weight_g_delta=weight_g,
        weight_ct_delta=weight_ct,
        reference_type=OPENING_STOCK_SOURCE,
        reference_id=item.id,
        notes=f"Opening stock{f' — {notes}' if notes else ''}",
        user_id=user_id,
    )
    return entry
