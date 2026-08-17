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
from app.core.units import carats_to_grams
from app.models.account import SystemAccount
from app.models.currency import Currency
from app.models.design import Design, JobLeg, LabourBasis, WastageBasis
from app.models.gold_rate import GoldRate
from app.models.item import Item
from app.models.journal import Commodity, JournalEntry, PartyType
from app.models.metal import Metal
from app.models.vendor import Vendor
from app.services.gold_rate import fine_rate_per_g, rate_in_force
from app.services.ledger import EntryDraft, Posting, d, fine_grams, post_entry, reverse_entry
from app.services.pricing import DEFAULT_RATTI_BASE

# Entries a leg posts are found again by this pair, which is how a cancel
# knows what to reverse.
SOURCE_TYPE = "job_leg"

# The number of pieces a setting wastage figure is quoted against when nobody
# says otherwise. A hundred is the common case, never the only one.
DEFAULT_PIECES_BASE = 100

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


async def next_lot_no(db: AsyncSession) -> str:
    """
    `LOT-NNNNN`, one global sequence.

    Not counted within the item, the way design numbers are. A lot is a dealing
    with a maker — a hundred grams and a due date — and while the metal is out
    the thing it will become is a plan, not a fact. Numbering it by item would
    put an identity on the row that the row cannot yet support.

    Same discipline as the design number: the next value comes from the highest
    suffix in use, so deleting a lot cannot cause its number to be handed out
    twice.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.LOT_NO))
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(Design.design_no, r"(\d+)$"), Integer)), 0
                )
            ).where(Design.design_no.like("LOT-%"))
        )
    ).scalar_one()
    return f"LOT-{int(highest) + 1:05d}"


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


async def current_gold_rate(db: AsyncSession, metal: Metal = Metal.gold) -> Decimal:
    """
    Today's PKR-per-fine-gram for this metal, valuing every gram the leg moves.

    Refusing to post without a rate is deliberate. Defaulting to zero would let
    a whole day's issues and receipts post at no value, and the books would
    balance perfectly while saying the shop moved nothing. Silver is held to
    the same rule rather than falling back to some standing figure: a metal
    valued at a number nobody set today is a metal nobody is watching.
    """
    rate = await rate_in_force(db, currency=Currency.PKR, purity=24, metal=metal)
    if rate is None or d(rate.rate_per_g) <= 0:
        quoted = "24k" if metal is Metal.gold else "999"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No {quoted} PKR {metal.value} rate is on record, so this movement cannot be "
            f"valued. Set today's {metal.value} rate first.",
        )
    return fine_rate_per_g(rate)


# The commodity a leg's metal posts in, and the two accounts it moves between.
# One table rather than a branch at each of the six posting sites: a leg that
# picked up the gold commodity and the silver account — or the reverse — would
# balance perfectly and be invisible in the trial balance.
_METAL_LEDGER = {
    Metal.gold: (Commodity.GOLD, SystemAccount.GOLD_IN_HAND, SystemAccount.GOLD_WITH_WORKERS),
    Metal.silver: (
        Commodity.SILVER,
        SystemAccount.SILVER_IN_HAND,
        SystemAccount.SILVER_WITH_WORKERS,
    ),
}


def metal_ledger(leg: JobLeg) -> tuple[Commodity, SystemAccount, SystemAccount]:
    """Which commodity and which pair of accounts this leg's metal lives in."""
    return _METAL_LEDGER[leg.metal or Metal.gold]


def agreed_wastage_pct(worker: Vendor | None) -> Decimal:
    """
    The allowance in force for this worker, resolved to a number at issue time.

    Never NULL. "Nothing was agreed" is a real answer meaning a zero allowance —
    the shop cannot have forgiven metal it never discussed — and storing that as
    NULL would leave the receive path unable to tell it apart from "not filled
    in yet", which is exactly the ambiguity that lets a live lookup creep back.
    """
    return d(worker.effective_wastage_pct) if worker is not None else Decimal("0")


def received_purity(leg: JobLeg) -> tuple[int | None, Decimal | None]:
    """
    The purity of what came *back*, as (karat, tunch %).

    Both are returned together and taken from the same end of the job, because
    `fine_grams` prefers tunch whenever it is present. Falling back field by
    field would let an issued tunch of 99.9 override an explicitly stated
    received karat of 21 — the piece would be valued as bullion and the maker
    credited with a fifth more metal than he handed over. So the received pair
    is used whole the moment *either* half of it is filled in, and the issued
    pair is used whole only when neither is.

    A leg written before these columns existed has both NULL and therefore
    keeps computing exactly as it always did.
    """
    if leg.gold_received_purity is not None or leg.gold_received_tunch_pct is not None:
        return leg.gold_received_purity, leg.gold_received_tunch_pct
    return leg.gold_issued_purity, leg.gold_issued_tunch_pct


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

    Three ways of agreeing the allowance, and they are not interchangeable:

    * percent_of_issued — allowed = issued * pct/100. What casting and
      goldsmithing work on.
    * per_100_pieces    — allowed = per_100 / 100 * pieces. What setting works
      on: 0.400g per hundred stones over 350 stones allows 1.400g. A setter's
      loss follows how many stones he handles, not how heavy the piece is, so
      charging him a percentage would under-charge a light piece carrying many
      stones and over-charge a heavy one carrying few.
    * ratti_of_received — allowed = received / 96 * ratti, in the karat he
      returned. The maker's convention: 6 ratti on 107.560g of 21k allows
      6.7225g of 21k, which is added to what he is credited with before the
      whole sum is converted to pure.

    Which end of the job the allowance is measured against is the part that
    makes these irreconcilable, and it is also what decides the *unit* the
    allowance is denominated in. A percentage of issued and a per-100 figure
    are grams of the metal that went out; a ratti of received is grams of the
    metal that came back, which is a different karat and therefore a different
    asset. Both are converted to fine below against their own purity — mixing
    them would subtract 21k grams from 24k grams and call the difference a
    shortfall.
    """
    issued = d(leg.gold_issued_g)
    received = d(leg.gold_received_g)
    actual = (issued - received).quantize(_G)
    recv_purity, recv_tunch = received_purity(leg)
    # The purity the allowance itself is denominated in — see the docstring.
    allow_purity, allow_tunch = leg.gold_issued_purity, leg.gold_issued_tunch_pct

    if leg.wastage_basis is WastageBasis.ratti_of_received:
        base = Decimal(str(leg.wastage_ratti_base or DEFAULT_RATTI_BASE))
        allowed = (received / base * d(leg.wastage_ratti)).quantize(_G)
        allow_purity, allow_tunch = recv_purity, recv_tunch
    elif leg.wastage_basis is WastageBasis.per_100_pieces:
        per_base = d(leg.wastage_per_100_pcs_g)
        # The base is whatever the deal was struck in, not always a hundred.
        # `or 100` covers legs written before the column existed, which were
        # all quoted per hundred — so nothing already settled moves.
        base = Decimal(str(leg.wastage_pieces_base or DEFAULT_PIECES_BASE))
        allowed = (per_base * Decimal(leg.piece_count or 0) / base).quantize(_G)
    else:
        pct = d(leg.wastage_allowed_pct)
        allowed = (issued * pct / Decimal("100")).quantize(_G)
        leg.wastage_allowed_pct = pct

    fine_issued = fine_grams(issued, leg.gold_issued_purity, leg.gold_issued_tunch_pct)
    fine_recv = fine_grams(received, recv_purity, recv_tunch)
    fine_allowed = fine_grams(allowed, allow_purity, allow_tunch)
    fine_actual = (fine_issued - fine_recv).quantize(_G)

    # Whether an unused allowance is money in the shop's pocket or metal the
    # worker is owed depends on what was agreed, and the two conventions differ.
    #
    # A percentage and a per-100 figure are *caps on liability*: the shop
    # forgives up to that much and no further. A setter who loses less than his
    # 1.400g keeps nothing extra — there was never a promise to give him metal,
    # only a promise not to charge him for some of it.
    #
    # A ratti of received is an *entitlement*. The maker's allowance is added to
    # what he is credited with, so if the piece comes back heavy enough that his
    # credit exceeds what he was issued, the shop genuinely owes him the
    # difference — he put his own metal, solder or findings into it. Flooring
    # that at zero would pocket his gold silently.
    if leg.wastage_basis is WastageBasis.ratti_of_received:
        excess = fine_actual - fine_allowed
    else:
        excess = max(fine_actual - fine_allowed, Decimal("0"))

    leg.wastage_allowed_fine_g = fine_allowed
    leg.wastage_actual_fine_g = fine_actual
    leg.wastage_excess_fine_g = excess

    leg.wastage_allowed_g = allowed
    if leg.wastage_basis is WastageBasis.ratti_of_received:
        # Restated in the karat the maker returned, because the raw subtraction
        # is meaningless here: 100g of 24k issued less 107.560g of 21k received
        # reads as a 7.560g *gain* on a job that is actually 0.0028g short. The
        # honest raw figure is the fine shortfall carried back into his karat,
        # so the screen shows "0.0032g of 21k short" rather than a windfall.
        factor = fine_grams(Decimal("1"), recv_purity, recv_tunch)
        leg.wastage_actual_g = (fine_actual / factor).quantize(_G) if factor else fine_actual
        leg.wastage_excess_g = (excess / factor).quantize(_G) if factor else excess
    else:
        leg.wastage_actual_g = actual
        leg.wastage_excess_g = max(actual - allowed, Decimal("0"))


def net_metal_g(gross_g: Decimal | float, stones_set_ct: Decimal | float) -> Decimal:
    """
    The metal in a returned piece, from what the scale said.

    A setter hands back one object. The gram figure on the scale is the metal
    plus the stones he set into it, and comparing that against the metal issued
    is comparing two different things: on a piece carrying 30ct the gross reads
    six grams heavy, which is four times any allowance the shop would agree, so
    a job that lost metal reads as one that gained it.

    The stones come back out at five carats to the gram — a definition, not a
    measurement. What is left is the only figure the wastage reckoning can use.
    """
    return (d(gross_g) - carats_to_grams(stones_set_ct)).quantize(_G)


def settle_stones(leg: JobLeg) -> None:
    """
    Account for every carat that went out, and write the totals on the leg.

    Four things can happen to an issued stone and each has a different
    consequence, so they are held apart rather than netted:

        issued = set + returned + broken + owed

    Set, returned and broken are stated at receive — the first because stones
    inside a finished piece cannot be weighed, the other two because they are
    physically on the counter. What remains is owed, and it is derived rather
    than typed so the identity cannot be broken: a fourth asserted figure could
    disagree with the other three and nothing would say which was wrong.

    Before this, the only question asked was how many came back. A stone that
    was neither returned nor set simply left the record — the shop could not
    tell a chipped diamond from a missing one, and neither produced a claim on
    anyone.
    """
    set_ct = returned_ct = broken_ct = owed_ct = Decimal("0")
    for line in leg.stones:
        set_ct += d(line.weight_set_ct)
        returned_ct += d(line.weight_returned_ct)
        broken_ct += d(line.weight_broken_ct)
        owed_ct += d(line.weight_owed_ct)

    leg.stones_set_ct = set_ct.quantize(_G)
    leg.stones_returned_ct = returned_ct.quantize(_G)
    leg.stones_broken_ct = broken_ct.quantize(_G)
    leg.stones_owed_ct = owed_ct.quantize(_G)
    # What the piece consumed. Set carats are what ended up in it; carats the
    # setter owes are gone from stock too, but they are his debt rather than
    # the piece's cost, and charging them to the piece would inflate what the
    # shop believes the article cost to make.
    leg.stones_used_ct = set_ct.quantize(_G)


def _allowance_terms(leg: JobLeg) -> str:
    """
    The deal, in the words it was struck in, for a ledger memo.

    Each basis is quoted in its own unit and printing the wrong one is how a
    statement becomes unreadable: a ratti leg has no percentage, so the memo
    that used to read "beyond None% agreed" told the reader nothing about what
    the maker had actually been allowed.
    """
    if leg.wastage_basis is WastageBasis.ratti_of_received:
        return f"{d(leg.wastage_ratti)} ratti of {leg.wastage_ratti_base or DEFAULT_RATTI_BASE}"
    if leg.wastage_basis is WastageBasis.per_100_pieces:
        base = leg.wastage_pieces_base or DEFAULT_PIECES_BASE
        return (
            f"{d(leg.wastage_per_100_pcs_g)}g per {base} over {leg.piece_count} pieces"
        )
    return f"{d(leg.wastage_allowed_pct)}%"


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
    commodity: Commodity = Commodity.GOLD,
    worker_id: int | None = None,
    native_g: Decimal | None = None,
    purity: int | None = None,
    tunch: Decimal | None = None,
    memo: str | None = None,
) -> Posting:
    return Posting(
        account_code=code.value,
        quantity=fine_g,
        commodity=commodity,
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
) -> JournalEntry:
    """Metal leaves the safe and becomes a claim on the worker holding it."""
    # Tunch is passed here as well as at receive. It is what `fine_grams`
    # prefers, so debiting the worker at karat and relieving him at tunch would
    # leave a residue on his account every time a leg carried an assay — a
    # balance that never closes on a job that physically did.
    fine = fine_grams(leg.gold_issued_g, leg.gold_issued_purity, leg.gold_issued_tunch_pct)
    commodity, in_hand, with_workers = metal_ledger(leg)
    who = worker.name if worker else "unassigned"
    draft = EntryDraft(
        memo=f"{design.design_no}: issued {d(leg.gold_issued_g)}g of "
        f"{(leg.metal or Metal.gold).value} to {who} ({leg.department.name})",
        source_type=SOURCE_TYPE,
        source_id=leg.id,
    )
    draft.add(
        _gold(
            with_workers,
            fine,
            rate,
            commodity=commodity,
            worker_id=leg.worker_id,
            native_g=d(leg.gold_issued_g),
            purity=leg.gold_issued_purity,
            tunch=leg.gold_issued_tunch_pct,
            memo=f"Issued on leg #{leg.sequence}",
        )
    )
    draft.add(
        _gold(
            in_hand,
            -fine,
            rate,
            commodity=commodity,
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

    The relief of the worker's account is computed from the issued weight and
    the issued purity — the same two figures the debit was posted from — so it
    is exactly that debit and his balance cannot drift by a rounding step per
    leg. What came *back* is converted at its own purity, which is the whole
    point: pure metal goes to a maker and 21k jewellery returns, and valuing
    the return at the issued purity credits him with about a seventh more gold
    than he handed over. The job then looks settled while the metal is short.

    The three fine figures are read off the leg, where `settle_wastage` wrote
    them, rather than recomputed here — one settlement, one set of numbers, and
    the screen showing the same reckoning the ledger posted. Legs written
    before those columns existed have them NULL and fall back to converting the
    raw columns exactly as this function always did.
    """
    issued_purity = leg.gold_issued_purity
    issued_tunch = leg.gold_issued_tunch_pct
    recv_purity, recv_tunch = received_purity(leg)
    commodity, in_hand, with_workers = metal_ledger(leg)

    fine_issued = fine_grams(leg.gold_issued_g, issued_purity, issued_tunch)
    fine_recv = fine_grams(leg.gold_received_g, recv_purity, recv_tunch)
    # Derived here rather than read off the leg so the three metal lines close
    # on their own arithmetic: what came back, plus what no longer exists, is
    # exactly what he was holding. `settle_wastage` computes the same figure
    # from the same two weights; taking it from the leg instead would let a
    # rounding step separate the posting from the relief and leave a residue on
    # the worker's account.
    fine_actual = fine_issued - fine_recv

    if leg.wastage_excess_fine_g is not None:
        fine_excess = d(leg.wastage_excess_fine_g)
    else:
        fine_allowed = fine_grams(leg.wastage_allowed_g, issued_purity, issued_tunch)
        fine_excess = max(fine_actual - fine_allowed, Decimal("0"))

    who = worker.name if worker else "unassigned"
    draft = EntryDraft(
        memo=f"{design.design_no}: received {d(leg.gold_received_g)}g from {who} "
        f"({leg.department.name})",
        source_type=SOURCE_TYPE,
        source_id=leg.id,
    )

    if fine_recv:
        draft.add(_gold(in_hand, fine_recv, rate, commodity=commodity,
                        native_g=d(leg.gold_received_g), purity=recv_purity,
                        tunch=recv_tunch))
    if fine_actual:
        draft.add(_gold(SystemAccount.WASTAGE_EXPENSE, fine_actual, rate,
                        commodity=commodity,
                        memo=f"Wastage on leg #{leg.sequence}"))
    # Nothing to relieve when nothing was issued — the maker worked on his own
    # gold and was never charged with any of the shop's. A zero line would be
    # harmless arithmetic and a lie on his statement, which would read as though
    # metal had been handed over and given back.
    if fine_issued:
        draft.add(
            _gold(
                with_workers,
                -fine_issued,
                rate,
                commodity=commodity,
                worker_id=leg.worker_id,
                native_g=-d(leg.gold_issued_g),
                purity=issued_purity,
                tunch=issued_tunch,
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
        # Signed, and the sign decides both the story and the account. Positive
        # is the ordinary case: he lost more than was agreed and owes it, which
        # is income the shop expects to recover. Negative only arises on the
        # maker's ratti, where the allowance is metal he is *entitled* to keep
        # rather than a cap on what he can be charged — a piece returned heavy
        # enough to overrun it means he put his own gold in, and the shop owes
        # him. Booking that as negative Wastage Recovered would report the debt
        # as reduced income; it is a cost of the job, so it goes to Wastage
        # Expense alongside the rest of the metal this leg consumed.
        counter = (
            SystemAccount.WASTAGE_RECOVERED if fine_excess > 0 else SystemAccount.WASTAGE_EXPENSE
        )
        draft.add(
            _gold(
                with_workers,
                fine_excess,
                rate,
                commodity=commodity,
                worker_id=leg.worker_id,
                purity=issued_purity,
                tunch=issued_tunch,
                memo=(
                    f"Beyond the {_allowance_terms(leg)} agreed — {abs(fine_excess)}g "
                    + ("owed by " if fine_excess > 0 else "owed to ")
                    + who
                ),
            )
        )
        draft.add(
            _gold(counter, -fine_excess, rate, commodity=commodity,
                  memo=f"Settled with {who}")
        )

    # Stones the worker cannot produce, charged in carats at what they would
    # have sold for.
    #
    # One line per material, because the rate is the rate of the stone actually
    # lost — a leg can carry thirty materials and an averaged rate would charge
    # him for a stone he never touched. The credit is a single rupee figure
    # against Wastage Recovered, the same account the gold shortfall goes to.
    #
    # Nothing is credited to 1140 Stone Inventory. Stone stock has never
    # entered the ledger — leg issues move stone stock with no posting behind
    # them, as `post_stocking` sets out — so relieving it here would invent a
    # balance in order to spend it. What is recorded is the claim, which is the
    # part that would otherwise be lost. It does mean the recovery shows gross
    # rather than net of what the stones cost; that is the honest consequence
    # of stones being a stock figure rather than a ledger one, and it is the
    # same trade `post_stocking` already makes.
    if leg.worker_id:
        stone_lines = [
            (line, d(line.weight_owed_ct), d(line.owed_rate_per_ct))
            for line in leg.stones
            if d(line.weight_owed_ct) > 0
        ]
        stone_value = sum((ct * r for _, ct, r in stone_lines), Decimal("0")).quantize(_PKR)
        # Gated on the carats, never on their value.
        #
        # A setter owes the stones he cannot produce whether or not anybody has
        # got round to pricing that grade. Gating on the rupee figure meant a
        # shop with no selling rate on a stone lost every claim silently — the
        # carats vanished from his account and from the books, which is the one
        # thing a carat sub-ledger exists to prevent. The claim is recorded at
        # whatever rate exists, including none; the rupee counter-line is what
        # is conditional, because a zero-value credit says nothing.
        if stone_lines:
            for line, owed_ct, owed_rate in stone_lines:
                draft.add(
                    Posting(
                        account_code=SystemAccount.STONES_WITH_WORKERS.value,
                        quantity=owed_ct,
                        commodity=Commodity.STONE,
                        rate=owed_rate,
                        party_type=PartyType.worker,
                        party_id=leg.worker_id,
                        memo=(
                            f"{owed_ct}ct of "
                            f"{line.stone.name if line.stone else 'stone'} unaccounted for "
                            f"on leg #{leg.sequence}"
                        ),
                    )
                )
            if stone_value:
                draft.add(
                    Posting(
                        SystemAccount.WASTAGE_RECOVERED.value,
                        -stone_value,
                        memo=f"Stones charged to {who}",
                    )
                )

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
        commodity, in_hand, with_workers = metal_ledger(leg)
        draft.add(
            _gold(
                with_workers,
                fine,
                rate,
                commodity=commodity,
                worker_id=leg.worker_id,
                native_g=outstanding,
                purity=leg.gold_issued_purity,
                tunch=leg.gold_issued_tunch_pct,
                memo="Outstanding after cancellation",
            )
        )
        draft.add(_gold(in_hand, -fine, rate, commodity=commodity,
                        native_g=-outstanding, purity=leg.gold_issued_purity,
                        tunch=leg.gold_issued_tunch_pct))
        entries.append(await post_entry(db, draft, user_id=user_id))
    return entries
