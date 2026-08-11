"""
The rules the workshop floor runs on.

Three things live here rather than in the router: the numbers a piece is
identified by, the wastage settlement, and the translation of a leg into
balanced journal entries. All three are business decisions that have to give
the same answer whoever asks — the API, a later import script, the e2e suite —
so they are not allowed to be spelled out at a call site.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import SystemAccount
from app.models.currency import Currency
from app.models.design import Design, JobLeg, LabourBasis, WastageBasis
from app.models.gold_rate import GoldRate
from app.models.item import Item
from app.models.journal import Commodity, JournalEntry, PartyType
from app.models.vendor import Vendor
from app.services.gold_rate import rate_in_force
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry, reverse_entry

# Entries a leg posts are found again by this pair, which is how a cancel
# knows what to reverse.
SOURCE_TYPE = "job_leg"

_G = Decimal("0.0001")
_PKR = Decimal("0.01")

# Design numbers are per-item counters, so the lock has to be per item too —
# minting a TK and an RG at the same moment must not serialise against each
# other. Tags are one global sequence and get their own key.
_DESIGN_LOCK_BASE = 7_400_000
_TAG_LOCK_KEY = 7_300_005


async def next_design_no(db: AsyncSession, item: Item) -> str:
    """
    `<ABBR>-<NNNNN>`, counted within the item.

    The next value comes from the highest suffix in use rather than a row
    count: delete TK-00003 out of five takas and a count-based mint would hand
    out TK-00005 again, which the unique index would then reject.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_DESIGN_LOCK_BASE + item.id)
    )
    prefix = item.abbreviation.upper()
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(Design.design_no, r"(\d+)$"), Integer)), 0
                )
            ).where(Design.design_no.like(f"{prefix}-%"))
        )
    ).scalar_one()
    return f"{prefix}-{int(highest) + 1:05d}"


async def next_tag_no(db: AsyncSession) -> str:
    """`TAG-YY-NNNNN`, same discipline as the design number."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_TAG_LOCK_KEY))
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(Design.tag_no, r"(\d+)$"), Integer)), 0
                )
            ).where(Design.tag_no.like(f"TAG-{year}-%"))
        )
    ).scalar_one()
    return f"TAG-{year}-{int(highest) + 1:05d}"


async def current_gold_rate(db: AsyncSession) -> Decimal:
    """
    Today's PKR-per-fine-gram, used to value every gram this leg moves.

    Refusing to post without a rate is deliberate. Defaulting to zero would let
    a whole day's issues and receipts post at no value, and the books would
    balance perfectly while saying the shop moved nothing.
    """
    rate = await rate_in_force(db, currency=Currency.PKR, purity=24)
    if rate is None or d(rate.rate_per_g) <= 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No 24k PKR gold rate is on record, so this movement cannot be valued. "
            "Set today's gold rate first.",
        )
    return d(rate.rate_per_g)


def agreed_wastage_pct(worker: Vendor | None) -> Decimal:
    """
    The allowance in force for this worker, resolved to a number at issue time.

    Never NULL. "Nothing was agreed" is a real answer meaning a zero allowance —
    the shop cannot have forgiven metal it never discussed — and storing that as
    NULL would leave the receive path unable to tell it apart from "not filled
    in yet", which is exactly the ambiguity that lets a live lookup creep back.
    """
    return d(worker.effective_wastage_pct) if worker is not None else Decimal("0")


def settle_wastage(leg: JobLeg) -> None:
    """
    Work out what the worker is actually liable for, and write it on the leg.

    The signs matter. `actual` is issued minus received and is *signed*: a
    negative figure means the piece came back heavier, which is what solder,
    alloy and findings do and is not a shortfall. Only the part beyond the
    allowance agreed with this worker is his — a shop that charges the whole
    difference is charging for metal it agreed he could lose.

    The terms are read only off the leg, never off the worker or department.
    They get renegotiated, and a live lookup here would judge metal against a
    deal struck after it left the safe — in both directions: a rate agreed
    later would retroactively excuse a shortfall, and a department default
    filled in afterwards would make a worker who was never on terms liable for
    the lot.

    Two ways of agreeing the allowance, and they are not interchangeable:

    * percent_of_issued — allowed = issued * pct/100. What casting and
      goldsmithing work on.
    * per_100_pieces    — allowed = per_100 / 100 * pieces. What setting works
      on: 0.400g per hundred stones over 350 stones allows 1.400g. A setter's
      loss follows how many stones he handles, not how heavy the piece is, so
      charging him a percentage would under-charge a light piece carrying many
      stones and over-charge a heavy one carrying few.
    """
    issued = d(leg.gold_issued_g)
    actual = (issued - d(leg.gold_received_g)).quantize(_G)

    if leg.wastage_basis is WastageBasis.per_100_pieces:
        per_100 = d(leg.wastage_per_100_pcs_g)
        allowed = (per_100 * Decimal(leg.piece_count or 0) / Decimal("100")).quantize(_G)
    else:
        pct = d(leg.wastage_allowed_pct)
        allowed = (issued * pct / Decimal("100")).quantize(_G)
        leg.wastage_allowed_pct = pct

    leg.wastage_allowed_g = allowed
    leg.wastage_actual_g = actual
    leg.wastage_excess_g = max(actual - allowed, Decimal("0"))


def compute_labour(leg: JobLeg) -> Decimal:
    """
    What the worker has earned on this leg.

    * per_gram  — on the weight he delivered, not what he was issued: he is
                  paid for the piece he produced.
    * per_piece — on the count he handled. Stone setting at 5 or 10 rupees a
                  stone, lacquering at 500 or 1000 an item.
    * flat      — the rate, whatever the leg carried.
    """
    rate = d(leg.labour_rate)
    if leg.labour_basis is LabourBasis.per_gram:
        return (rate * d(leg.gold_received_g)).quantize(_PKR)
    if leg.labour_basis is LabourBasis.per_piece:
        return (rate * Decimal(leg.piece_count or 0)).quantize(_PKR)
    return rate.quantize(_PKR)


def _gold(
    code: SystemAccount,
    fine_g: Decimal,
    rate: Decimal,
    *,
    worker_id: int | None = None,
    native_g: Decimal | None = None,
    purity: int | None = None,
    memo: str | None = None,
) -> Posting:
    return Posting(
        account_code=code.value,
        quantity=fine_g,
        commodity=Commodity.GOLD,
        rate=rate,
        party_type=PartyType.worker if worker_id else None,
        party_id=worker_id,
        native_weight_g=native_g,
        native_purity=purity,
        memo=memo,
    )


async def post_leg_issue(
    db: AsyncSession,
    leg: JobLeg,
    *,
    design: Design,
    worker: Vendor | None,
    rate: Decimal,
    user_id: int | None = None,
) -> JournalEntry:
    """Metal leaves the safe and becomes a claim on the worker holding it."""
    fine = fine_grams(leg.gold_issued_g, leg.gold_issued_purity)
    who = worker.name if worker else "unassigned"
    draft = EntryDraft(
        memo=f"{design.design_no}: issued {d(leg.gold_issued_g)}g to {who} ({leg.department.name})",
        source_type=SOURCE_TYPE,
        source_id=leg.id,
    )
    draft.add(
        _gold(
            SystemAccount.GOLD_WITH_WORKERS,
            fine,
            rate,
            worker_id=leg.worker_id,
            native_g=d(leg.gold_issued_g),
            purity=leg.gold_issued_purity,
            memo=f"Issued on leg #{leg.sequence}",
        )
    )
    draft.add(
        _gold(
            SystemAccount.GOLD_IN_HAND,
            -fine,
            rate,
            native_g=-d(leg.gold_issued_g),
            purity=leg.gold_issued_purity,
        )
    )
    return await post_entry(db, draft, user_id=user_id)


async def post_leg_receive(
    db: AsyncSession,
    leg: JobLeg,
    *,
    design: Design,
    worker: Vendor | None,
    rate: Decimal,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Settle the leg: metal back into stock, wastage split, labour accrued.

    The worker is relieved of exactly what was issued to him — the piece he
    returned plus the metal that no longer exists — and is then re-charged the
    part of that loss he had not been allowed. Doing it in two movements rather
    than one netted figure is what leaves 5200 carrying the agreed cost of
    production and 4200 carrying what the shop intends to claim back, instead
    of a single number that hides both.

    Fine grams are derived from the issued figure rather than re-converted from
    each weight column, so the relief is exactly the debit posted at issue and
    a worker's gold balance cannot drift by a rounding step per leg.
    """
    purity = leg.gold_issued_purity
    fine_issued = fine_grams(leg.gold_issued_g, purity)
    fine_recv = fine_grams(leg.gold_received_g, purity)
    fine_actual = fine_issued - fine_recv
    fine_allowed = fine_grams(leg.wastage_allowed_g, purity)
    fine_excess = max(fine_actual - fine_allowed, Decimal("0"))

    who = worker.name if worker else "unassigned"
    draft = EntryDraft(
        memo=f"{design.design_no}: received {d(leg.gold_received_g)}g from {who} "
        f"({leg.department.name})",
        source_type=SOURCE_TYPE,
        source_id=leg.id,
    )

    if fine_recv:
        draft.add(_gold(SystemAccount.GOLD_IN_HAND, fine_recv, rate,
                        native_g=d(leg.gold_received_g), purity=purity))
    if fine_actual:
        draft.add(_gold(SystemAccount.WASTAGE_EXPENSE, fine_actual, rate,
                        memo=f"Wastage on leg #{leg.sequence}"))
    draft.add(
        _gold(
            SystemAccount.GOLD_WITH_WORKERS,
            -fine_issued,
            rate,
            worker_id=leg.worker_id,
            native_g=-d(leg.gold_issued_g),
            purity=purity,
            memo=f"Relieved on leg #{leg.sequence}",
        )
    )
    if fine_excess:
        draft.add(
            _gold(
                SystemAccount.GOLD_WITH_WORKERS,
                fine_excess,
                rate,
                worker_id=leg.worker_id,
                purity=purity,
                memo=f"Wastage beyond {d(leg.wastage_allowed_pct)}% agreed — {fine_excess}g owed",
            )
        )
        draft.add(_gold(SystemAccount.WASTAGE_RECOVERED, -fine_excess, rate,
                        memo=f"Charged to {who}"))

    labour = d(leg.labour_amount)
    if labour:
        draft.add(Posting(SystemAccount.LABOUR_COST.value, labour, memo=f"Labour — {who}"))
        draft.add(
            Posting(
                SystemAccount.WORKERS_PAYABLE.value,
                -labour,
                party_type=PartyType.worker if leg.worker_id else None,
                party_id=leg.worker_id,
                memo=f"{design.design_no} leg #{leg.sequence}",
            )
        )
    return await post_entry(db, draft, user_id=user_id)


async def post_leg_cancel(
    db: AsyncSession,
    leg: JobLeg,
    *,
    design: Design,
    worker: Vendor | None,
    gold_recovered_g: Decimal,
    rate: Decimal,
    user_id: int | None = None,
) -> list[JournalEntry]:
    """
    Undo the leg's accounting, then re-state what is still out there.

    The reversals put the books back where they were before the leg, which is
    the only honest thing to do with an abandoned leg. But the metal the shop
    did not physically get back is still with the worker, so it is posted again
    as a claim on him — otherwise cancelling a leg would quietly forgive the
    material, which is exactly the hole this rewrite exists to close.
    """
    entries: list[JournalEntry] = []
    originals = (
        (
            await db.execute(
                select(JournalEntry)
                .where(
                    JournalEntry.source_type == SOURCE_TYPE,
                    JournalEntry.source_id == leg.id,
                    JournalEntry.reverses_entry_id.is_(None),
                )
                .order_by(JournalEntry.id)
            )
        )
        .scalars()
        .all()
    )
    for original in originals:
        entries.append(
            await reverse_entry(
                db,
                original,
                memo=f"Cancelled leg #{leg.sequence} on {design.design_no}",
                user_id=user_id,
            )
        )

    outstanding = (d(leg.gold_issued_g) - d(gold_recovered_g)).quantize(_G)
    if outstanding > 0:
        who = worker.name if worker else "unassigned"
        fine = fine_grams(outstanding, leg.gold_issued_purity)
        draft = EntryDraft(
            memo=f"{design.design_no}: {outstanding}g not recovered from {who} on cancellation",
            source_type=SOURCE_TYPE,
            source_id=leg.id,
        )
        draft.add(
            _gold(
                SystemAccount.GOLD_WITH_WORKERS,
                fine,
                rate,
                worker_id=leg.worker_id,
                native_g=outstanding,
                purity=leg.gold_issued_purity,
                memo="Outstanding after cancellation",
            )
        )
        draft.add(_gold(SystemAccount.GOLD_IN_HAND, -fine, rate,
                        native_g=-outstanding, purity=leg.gold_issued_purity))
        entries.append(await post_entry(db, draft, user_id=user_id))
    return entries
