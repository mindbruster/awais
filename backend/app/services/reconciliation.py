"""
Comparing what the books say with what is on the scale, and posting the gap.

The rule this module exists to keep: **a count never overwrites a balance.** It
posts a movement and a journal entry, carrying a reason and a name, exactly as a
purchase does. A stock figure you can type over is a stock figure nobody can
audit, and it would make every other guarantee in this system worthless.

Two figures, and they are not the same thing:

* **As-weighed grams** are what the pot holds and what the scale reads. A
  variance is discovered in these.
* **Fine grams** are what the ledger carries. The variance is converted at the
  pot's own purity before it touches the books, because 2.6 g missing from a
  22k pot is 2.3833 fine grams and booking it as 2.6 would leave the trial
  balance out by the alloy.

Metals only, deliberately. Stones would need a variance valued out of the FIFO
parcels they were bought in, and cash is reconciled against a bank statement
rather than a scale — different machinery, and guessing at either here would
produce a number that looks authoritative and is not.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, lock_keys
from app.core.config import settings
from app.models.account import SystemAccount
from app.models.inventory import InventoryItem, InventoryType
from app.models.journal import Commodity, JournalEntry
from app.models.metal import Metal
from app.models.stock_count import StockCount, StockCountLine, StockCountStatus
from app.models.stock_movement import MovementType
from app.services.gold_rate import fine_rate_per_g, rate_in_force
from app.services.inventory import post_movement
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry

STOCK_COUNT_SOURCE = "stock_count"

_G = Decimal("0.0001")
_PKR = Decimal("0.01")
_ZERO = Decimal("0")

# What each metal is held in, counted as, and posted to.
_METAL = {
    Metal.gold: (InventoryType.raw_gold, Commodity.GOLD, SystemAccount.GOLD_IN_HAND),
    Metal.silver: (InventoryType.raw_silver, Commodity.SILVER, SystemAccount.SILVER_IN_HAND),
}


async def next_count_no(db: AsyncSession) -> str:
    """`SC-<YY>-<NNNNN>`, serialised so two counters cannot be handed one number."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.STOCK_COUNT_NO)
    )
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(StockCount.count_no, r"(\d+)$"), Integer)), 0
                )
            ).where(StockCount.count_no.like(f"SC-{year}-%"))
        )
    ).scalar_one()
    return f"SC-{year}-{int(highest) + 1:05d}"


async def pots_for(db: AsyncSession, *, metal: Metal, branch_id: int) -> list[InventoryItem]:
    """
    Every melt pot of this metal at this branch, in a stable order.

    Includes pots holding nothing. A pot the books say is empty is exactly the
    one worth putting on the sheet: if there is metal in it, nobody would ever
    have gone looking.
    """
    inv_type, _, _ = _METAL[metal]
    return list(
        (
            await db.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.type == inv_type,
                    InventoryItem.branch_id == branch_id,
                )
                .order_by(InventoryItem.purity.desc().nullslast(), InventoryItem.id)
            )
        )
        .unique()
        .scalars()
        .all()
    )


def line_variance(line: StockCountLine) -> Decimal | None:
    """
    Counted less book, as weighed. `None` when the pot has not been weighed.

    Negative is short — the usual direction, and the one that costs money.
    """
    if line.counted_weight_g is None:
        return None
    return (d(line.counted_weight_g) - d(line.book_weight_g)).quantize(_G)


def item_fine(item: InventoryItem, weight_g: Decimal) -> Decimal:
    """As-weighed grams of this pot, in the fine grams the ledger carries."""
    return fine_grams(weight_g, item.purity, item.tunch_pct)


@dataclass
class Variance:
    """What one line's difference amounts to, in both units."""

    line: StockCountLine
    item: InventoryItem
    weight_g: Decimal
    fine_g: Decimal


def variances(count: StockCount) -> list[Variance]:
    """Only the lines that actually differ — a matching pot posts nothing."""
    out: list[Variance] = []
    for line in count.lines:
        delta = line_variance(line)
        if delta is None or delta == 0:
            continue
        item = line.item
        out.append(
            Variance(
                line=line,
                item=item,
                weight_g=delta,
                fine_g=item_fine(item, delta).quantize(_G),
            )
        )
    return out


def assert_complete(count: StockCount) -> None:
    """
    The two things a sheet needs before anybody signs it.

    Shared between submitting and posting so the counter meets them at the
    counter rather than the approver meeting them an hour later — a control
    that fails at the last step teaches people to route around it.
    """
    if not (count.reason or "").strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Say why the books were wrong before writing the difference off. A variance "
            "with no explanation is the first thing an auditor asks about.",
        )
    if any(line.counted_weight_g is None for line in count.lines):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Every pot on the sheet has to be weighed before it is posted. An unweighed "
            "pot is not an empty one, and posting it as zero would write the whole pot off.",
        )


def assert_second_person(count: StockCount, user_id: int | None) -> None:
    """
    Four eyes on a metal write-off, when the shop has asked for it.

    Checked against whoever *submitted* the figures rather than whoever opened
    the sheet: a count started in the morning and finished by the evening shift
    is ordinary, and the person asserting what the scale said is the one whose
    word is being taken.

    Silent when `REQUIRE_TWO_PERSON_APPROVAL` is off, which is the default. A
    single-admin shop would otherwise be unable to post a count at all — a
    control that makes the feature unusable pushes the reconciliation back onto
    paper, which is strictly worse than not having the control.
    """
    if not settings.require_two_person_approval:
        return
    if count.status is not StockCountStatus.submitted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{count.count_no} has to be submitted for approval before it can be posted. "
            "This shop requires a second person on a metal write-off.",
        )
    asserted_by = count.submitted_by_user_id or count.created_by_user_id
    if asserted_by is not None and user_id is not None and asserted_by == user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You counted this metal, so you cannot also accept the loss. This shop "
            "requires a second person to approve a stock write-off — ask a colleague "
            "to post it.",
        )


def submit_count(count: StockCount, *, user_id: int | None = None) -> None:
    """
    Hand a finished sheet to whoever approves it.

    A separate act from posting, and it exists so the approver has a queue.
    Without it there is no difference between a sheet half-filled and one ready
    to sign, and the second person would have to open every draft to find out.
    """
    if count.status is not StockCountStatus.draft:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{count.count_no} is {count.status.value} and is not waiting to be submitted.",
        )
    assert_complete(count)
    count.status = StockCountStatus.submitted
    count.submitted_by_user_id = user_id
    count.submitted_at = datetime.now(timezone.utc)


async def post_count(
    db: AsyncSession,
    count: StockCount,
    *,
    user_id: int | None = None,
) -> JournalEntry | None:
    """
    Accept the count: move the stock, and book the difference.

    Returns `None` when nothing differed, which is a real outcome and the one
    the shop hopes for — it must not read as a failure.

    The stock side and the books side are one transaction. A count that adjusted
    the pot without telling the ledger would leave the two describing different
    shops, which is the precise failure a stock-take exists to detect.
    """
    if count.status not in (StockCountStatus.draft, StockCountStatus.submitted):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{count.count_no} is already {count.status.value} and cannot be posted again.",
        )
    assert_complete(count)
    assert_second_person(count, user_id)

    diffs = variances(count)
    if not diffs:
        # Nothing moved and nothing is booked, but the sheet is still closed —
        # "we counted and it agreed" is a fact worth keeping.
        count.status = StockCountStatus.posted
        count.posted_by_user_id = user_id
        count.posted_at = datetime.now(timezone.utc)
        return None

    _, commodity, in_hand = _METAL[count.metal]

    # Valued at the rate in force, per *fine* gram. Refused rather than booked
    # at zero when there is no rate: a write-off valued at nothing is a loss the
    # profit and loss account never hears about.
    rate_row = await rate_in_force(db, metal=count.metal, as_of=clock.today())
    if rate_row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No {count.metal.value} rate is on record, so a variance cannot be valued. "
            "Set today's rate first — writing metal off at zero would hide the loss.",
        )
    rate = fine_rate_per_g(rate_row)

    draft = EntryDraft(
        memo=f"{count.count_no}: {count.metal.value} stock count — {count.reason}"[:255],
        entry_date=clock.shop_date(count.counted_at),
        source_type=STOCK_COUNT_SOURCE,
        source_id=count.id,
    )

    total_fine = _ZERO
    for v in diffs:
        total_fine += v.fine_g
        # The metal account moves by the fine variance, signed: negative is
        # metal that is not there, and credits the asset.
        draft.add(
            Posting(
                account_code=in_hand.value,
                quantity=v.fine_g,
                commodity=commodity,
                rate=rate,
                native_weight_g=v.weight_g,
                native_purity=v.item.purity,
                memo=(
                    f"{v.item.label}: counted {d(v.line.counted_weight_g)}g against "
                    f"{d(v.line.book_weight_g)}g on the books"
                ),
            )
        )

    value = (total_fine * rate).quantize(_PKR)
    if value != 0:
        draft.add(
            Posting(
                account_code=SystemAccount.STOCK_VARIANCE.value,
                # Opposite sign to the metal: metal short is an expense, metal
                # found reduces one. One account both ways — see the model.
                quantity=-value,
                memo=(
                    f"{'Short' if total_fine < 0 else 'Over'} on {count.count_no} "
                    f"({total_fine} fine g at {rate}/g)"
                ),
            )
        )

    entry = await post_entry(db, draft, user_id=user_id)

    # Stock second, and only after the books accepted the entry — so a count
    # that cannot be booked does not move the pot either.
    for v in diffs:
        await post_movement(
            db,
            item=v.item,
            type=MovementType.adjustment,
            weight_g_delta=v.weight_g,
            reference_type=STOCK_COUNT_SOURCE,
            reference_id=count.id,
            notes=f"{count.count_no} stock count — {count.reason}"[:255],
            user_id=user_id,
        )

    count.status = StockCountStatus.posted
    count.posted_by_user_id = user_id
    count.posted_at = datetime.now(timezone.utc)
    count.journal_entry_id = entry.id
    return entry
