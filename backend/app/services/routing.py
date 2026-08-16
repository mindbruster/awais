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

from app.core import lock_keys
from app.models.account import SystemAccount
from app.models.currency import Currency
from app.models.design import Design, JobLeg, LabourBasis, WastageBasis
from app.models.gold_rate import GoldRate
from app.models.item import Item
from app.models.journal import Commodity, JournalEntry, PartyType
from app.models.vendor import Vendor
from app.services.gold_rate import rate_in_force
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry, reverse_entry
from app.services.pricing import DEFAULT_RATTI_BASE, ratti_allowance

# Entries a leg posts are found again by this pair, which is how a cancel
# knows what to reverse.
SOURCE_TYPE = "job_leg"

_G = Decimal("0.0001")
_PKR = Decimal("0.01")

# Design numbers are per-item counters, so the lock has to be per item too —
# minting a TK and an RG at the same moment must not serialise against each
# other. Tags are one global sequence and get their own key.
_DESIGN_LOCK_BASE = lock_keys.DESIGN_NO_BASE
_TAG_LOCK_KEY = lock_keys.TAG_NO


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


def received_metal(leg: JobLeg) -> tuple[int | None, Decimal | None]:
    """
    What the metal that came *back* was, as a (karat, tunch) pair.

    A different question from what went out, and the system used to assume it
    was the same one. Pure 24k goes to the maker and 21k jewellery comes back;
    valuing that return at the *issued* purity credited the piece as though it
    were pure and overstated what he had delivered by about fourteen percent.
    The shop would read a job as settled while the metal was still short.

    The two columns are read as a pair. Filling in either one means "this is
    what came back", and the other half is then deliberately not borrowed from
    the issue side — a leg that says 21 karat must not also inherit a tunch of
    99.9, which wins over the karat in `fine_grams` and would undo the very
    correction the caller was making.

    Both empty means nothing was said, which is the ordinary case and the
    honest reading of it: the same metal came back as went out. Those legs
    compute exactly as they did before this column existed, so nothing already
    settled moves.
    """
    if leg.gold_received_purity is None and leg.gold_received_tunch_pct is None:
        return leg.gold_issued_purity, leg.gold_issued_tunch_pct
    return leg.gold_received_purity, leg.gold_received_tunch_pct


def fine_issued_g(leg: JobLeg) -> Decimal:
    """The metal that left the safe, in fine grams."""
    return fine_grams(leg.gold_issued_g, leg.gold_issued_purity, leg.gold_issued_tunch_pct)


def fine_received_g(leg: JobLeg) -> Decimal:
    """The metal that came back, in fine grams — at *its own* purity."""
    purity, tunch = received_metal(leg)
    return fine_grams(leg.gold_received_g, purity, tunch)


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

    Three ways of agreeing the allowance, and none converts into another:

    * percent_of_issued  — allowed = issued * pct/100. What casting and
      goldsmithing work on.
    * per_100_pieces     — allowed = per_100 / 100 * pieces. What setting works
      on: 0.400g per hundred stones over 350 stones allows 1.400g. A setter's
      loss follows how many stones he handles, not how heavy the piece is, so
      charging him a percentage would under-charge a light piece carrying many
      stones and over-charge a heavy one carrying few.
    * ratti_of_received  — allowed = returned / 96 * ratti. What the maker works
      on, and the odd one out: it is measured against the weight he *hands
      back*, not the weight he was issued, so until the job is finished the
      allowance is not a knowable number.

    Everything is written twice — once as the scale read it, once in fine grams.

    The raw columns compare grams to grams, which means something only while
    both ends of the job are the same purity. The maker's leg is not: 24k goes
    out and 21k comes back, and 107.560 raw grams against 100 raw grams issued
    reads as the piece coming back *heavier* when in fact the metal is square.
    Subtracting one from the other is subtracting different assets. So the
    liability is settled on the fine columns, and the raw ones are kept as what
    the scale actually said — which is what the worker will argue from.
    """
    issued = d(leg.gold_issued_g)
    received = d(leg.gold_received_g)
    actual = (issued - received).quantize(_G)

    if leg.wastage_basis is WastageBasis.ratti_of_received:
        allowed = ratti_allowance(
            received,
            d(leg.wastage_ratti),
            int(leg.wastage_ratti_base or DEFAULT_RATTI_BASE),
        )
    elif leg.wastage_basis is WastageBasis.per_100_pieces:
        per_100 = d(leg.wastage_per_100_pcs_g)
        allowed = (per_100 * Decimal(leg.piece_count or 0) / Decimal("100")).quantize(_G)
    else:
        pct = d(leg.wastage_allowed_pct)
        allowed = (issued * pct / Decimal("100")).quantize(_G)
        leg.wastage_allowed_pct = pct

    leg.wastage_allowed_g = allowed
    leg.wastage_actual_g = actual
    leg.wastage_excess_g = max(actual - allowed, Decimal("0"))

    # The allowance is converted at the purity of the metal it was measured
    # against, which is the whole reason the basis has to be known here. A ratti
    # allowance is a slice of the jewellery the maker hands back, so it is 21k
    # metal; a percentage or a per-100 figure is carved out of what he was
    # issued, so it is 24k. Converting either at the wrong end would quietly
    # move the allowance by the difference between the two purities.
    fine_issued = fine_issued_g(leg)
    fine_received = fine_received_g(leg)
    if leg.wastage_basis is WastageBasis.ratti_of_received:
        purity, tunch = received_metal(leg)
        fine_allowed = fine_grams(allowed, purity, tunch)
    else:
        fine_allowed = fine_grams(allowed, leg.gold_issued_purity, leg.gold_issued_tunch_pct)

    # Metal the worker put in himself is not metal the job lost, so it comes
    # out of the reckoning before anything is called wastage. Without this a
    # piece made on his own gold reports a hundred-gram *gain* against a job
    # that consumed nothing, and every loss report it lands in reads that as
    # the shop having won metal back off its karigars.
    #
    # The same netting the ledger does when it posts the leg, kept here so the
    # column and the entry cannot drift apart.
    fine_supplied = (
        max(fine_received - fine_issued, Decimal("0"))
        if leg.metal_on_credit and leg.worker_id
        else Decimal("0")
    )
    fine_actual = (fine_issued - fine_received + fine_supplied).quantize(_G)
    leg.wastage_allowed_fine_g = fine_allowed
    leg.wastage_actual_fine_g = fine_actual
    leg.wastage_excess_fine_g = max(fine_actual - fine_allowed, Decimal("0"))


def agreed_terms(leg: JobLeg) -> str:
    """
    The allowance in the words it was agreed in, for the memo on the charge.

    A worker reads "beyond 2% agreed" and knows which deal is being invoked.
    Printing the percentage on every leg regardless of basis — which is what
    this used to do — told a setter he had exceeded a percentage nobody had
    ever quoted him, and told a maker the same about a figure that was zero on
    his leg because his deal is not written in percent.
    """
    if leg.wastage_basis is WastageBasis.ratti_of_received:
        return (
            f"{d(leg.wastage_ratti)} ratti of {int(leg.wastage_ratti_base or DEFAULT_RATTI_BASE)} "
            "on the weight returned"
        )
    if leg.wastage_basis is WastageBasis.per_100_pieces:
        return f"{d(leg.wastage_per_100_pcs_g)}g per 100 pieces agreed"
    return f"{d(leg.wastage_allowed_pct)}% agreed"


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
    tunch: Decimal | None = None,
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
        native_tunch_pct=tunch,
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
) -> JournalEntry | None:
    """
    Metal leaves the safe and becomes a claim on the worker holding it.

    None when no metal leaves, which is a real leg: the worker is making the
    piece on his own gold. There is nothing to claim off him and nothing to
    relieve the safe of, and posting the pair of zeroes anyway would leave the
    ledger carrying an entry that says nothing happened — findable by anyone
    later auditing what this leg moved, and answering wrongly.
    """
    fine = fine_issued_g(leg)
    if not fine:
        return None
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
            tunch=leg.gold_issued_tunch_pct,
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
            tunch=leg.gold_issued_tunch_pct,
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

    The relief of the worker's account is the issued figure exactly — the same
    number that was debited to him when the metal left — so a balance cannot
    drift by a rounding step per leg. What he returned is converted at *its own*
    purity, which is the correction this used to get wrong: 21k jewellery
    credited at 24k relieved him of metal he had not delivered.

    Everything below is in fine grams, and the identity that keeps the entry
    balanced is unchanged: what came back plus what was lost equals what went
    out, because the loss is defined as the difference between the other two.
    A leg made on the worker's own metal adds one term to that identity — what
    he supplied — and it is a credit to his account rather than a loss.
    """
    purity = leg.gold_issued_purity
    recv_purity, recv_tunch = received_metal(leg)
    fine_issued = fine_issued_g(leg)
    fine_recv = fine_received_g(leg)
    fine_actual = fine_issued - fine_recv
    # Written by `settle_wastage` at the purity the deal was struck against.
    # Legs settled before that column existed have nothing here and fall back to
    # converting the raw figure at the issued purity, exactly as they always
    # did — so a re-post of an old leg reproduces its original entry.
    fine_allowed = (
        d(leg.wastage_allowed_fine_g)
        if leg.wastage_allowed_fine_g is not None
        else fine_grams(leg.wastage_allowed_g, purity, leg.gold_issued_tunch_pct)
    )
    fine_excess = max(fine_actual - fine_allowed, Decimal("0"))

    # Metal the worker put in out of his own stock, which the shop now holds and
    # owes back. Only on a leg struck that way: a piece that comes back heavier
    # off an ordinary leg has gained solder, alloy and findings, and that metal
    # is the shop's. The two are indistinguishable by weight — both read as more
    # returned than issued — so the flag decides, never the arithmetic.
    #
    # Requires a worker for the same reason the excess re-charge does: the
    # credit has to land on somebody's account or it is a balance with no party
    # to hand it back to. The API refuses the combination outright, and this is
    # the second lock on it.
    fine_supplied = (
        max(fine_recv - fine_issued, Decimal("0"))
        if leg.metal_on_credit and leg.worker_id
        else Decimal("0")
    )
    # Netted out of the wastage line rather than posted beside it. What the
    # worker supplied was never a loss, and leaving it in 5200 would report a
    # negative cost of production — the shop appearing to *earn* wastage on a
    # job where it lost none.
    fine_wastage = fine_actual + fine_supplied

    who = worker.name if worker else "unassigned"
    draft = EntryDraft(
        memo=f"{design.design_no}: received {d(leg.gold_received_g)}g from {who} "
        f"({leg.department.name})",
        source_type=SOURCE_TYPE,
        source_id=leg.id,
    )

    if fine_recv:
        draft.add(_gold(SystemAccount.GOLD_IN_HAND, fine_recv, rate,
                        native_g=d(leg.gold_received_g), purity=recv_purity,
                        tunch=recv_tunch))
    if fine_wastage:
        draft.add(_gold(SystemAccount.WASTAGE_EXPENSE, fine_wastage, rate,
                        memo=f"Wastage on leg #{leg.sequence}"))
    # The worker's own metal, now in the shop's safe and owed back to him. It
    # goes to the same account his issues do, which swings negative to say the
    # debt runs the other way — the shop is holding his gold. A separate
    # liability account would split one man's metal position in two, and this
    # trade settles it as one running figure.
    if fine_supplied:
        draft.add(
            _gold(
                SystemAccount.GOLD_WITH_WORKERS,
                -fine_supplied,
                rate,
                worker_id=leg.worker_id,
                purity=recv_purity,
                tunch=recv_tunch,
                memo=(
                    f"{who}'s own metal on leg #{leg.sequence}"
                    + (f", due {leg.metal_due_date}" if leg.metal_due_date else "")
                ),
            )
        )
    # Nothing to relieve when nothing was issued, which is the credit leg. The
    # zero line would balance perfectly and say the maker had been let off a
    # debt he never had — and it would sit in his statement alongside the real
    # credit above, which is where somebody reading it would trip.
    if fine_issued:
        draft.add(
            _gold(
                SystemAccount.GOLD_WITH_WORKERS,
                -fine_issued,
                rate,
                worker_id=leg.worker_id,
                native_g=-d(leg.gold_issued_g),
                purity=purity,
                tunch=leg.gold_issued_tunch_pct,
                memo=f"Relieved on leg #{leg.sequence}",
            )
        )
    # Re-charging the excess only makes sense when somebody agreed to an
    # allowance in the first place. On an in-house leg there is no such
    # agreement and nobody to bill, so the metal simply stays where the line
    # above put it — Wastage Expense, the shop's own cost of production.
    # Posting the re-charge anyway would credit Wastage Recovered, booking
    # income against a debt owed by no one, and leave a balance sitting in the
    # worker control account with no party to attribute it to.
    if fine_excess and leg.worker_id:
        draft.add(
            _gold(
                SystemAccount.GOLD_WITH_WORKERS,
                fine_excess,
                rate,
                worker_id=leg.worker_id,
                purity=purity,
                memo=f"Wastage beyond {agreed_terms(leg)} — {fine_excess}g owed",
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
        fine = fine_grams(outstanding, leg.gold_issued_purity, leg.gold_issued_tunch_pct)
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
                tunch=leg.gold_issued_tunch_pct,
                memo="Outstanding after cancellation",
            )
        )
        draft.add(_gold(SystemAccount.GOLD_IN_HAND, -fine, rate,
                        native_g=-outstanding, purity=leg.gold_issued_purity,
                        tunch=leg.gold_issued_tunch_pct))
        entries.append(await post_entry(db, draft, user_id=user_id))
    return entries
