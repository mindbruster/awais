"""
Non-destructive smoke test for the maker's leg.

Four rules the shop works to that the leg had no room for, and the shop's own
worked example is the fixture: **100g of pure 24k out, 107.560g of 21k back, six
ratti of wastage — and the job is square.**

Every one of those numbers has to survive.

**What came back is not what went out.** The system valued the returned weight
at the *issued* purity, so 107.560g of 21k was credited as 107.560g of pure —
about fourteen percent more metal than the maker actually delivered. The shop
would read the job as settled, and better than settled, while the metal was
still short.

**The maker's wastage is ratti, on the weight returned.** Six of ninety-six on
107.560g allows 6.7225g, added to what he is credited with. Neither the
goldsmith's percentage nor the setter's per-hundred can express that, because
both are measured against what went out — a number known at the wrong end of
the job.

**Grams stopped being comparable.** 100 issued against 107.560 returned reads as
the piece coming back seven grams *heavier* when in truth the metal is square.
The liability has to be settled in fine grams; the raw figures are kept as what
the scale said.

**The metal is not always the shop's.** A maker who works on his own gold is
owed it back, and that is a credit to his account — not free alloy, which is
what the arithmetic alone would have called it.

The old conventions are asserted alongside the new ones. A leg that says
nothing about what came back has to settle exactly as it did before any of this
existed, or every job already closed moves.

Everything that touches the database runs inside a transaction that is rolled
back, so the developer's database is left as it was found.
"""
import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

logging.disable(logging.INFO)

from app.core.database import SessionLocal  # noqa: E402
from app.models.account import SystemAccount  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.design import (  # noqa: E402
    Design,
    DesignStatus,
    JobLeg,
    LabourBasis,
    LegStatus,
    WastageBasis,
)
from app.models.item import Item  # noqa: E402
from app.models.journal import Commodity, JournalLine, PartyType  # noqa: E402
from app.models.metal import Metal  # noqa: E402
from app.models.vendor import Vendor, VendorType  # noqa: E402
from app.services.ledger import d, fine_grams  # noqa: E402
from app.services.pricing import ratti_allowance  # noqa: E402
from app.services.routing import (  # noqa: E402
    agreed_terms,
    fine_received_g,
    post_leg_receive,
    settle_wastage,
)

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


def maker_leg(**overrides) -> JobLeg:
    """
    The shop's worked example, in memory.

    Not flushed: `settle_wastage` reads and writes columns and touches nothing
    else, so the arithmetic can be pinned without a database at all — which is
    the point, because these are the numbers the shop quoted and they must not
    depend on what happens to be seeded.
    """
    leg = JobLeg(
        sequence=1,
        gold_issued_g=Decimal("100"),
        gold_issued_purity=24,
        gold_received_g=Decimal("107.560"),
        gold_received_purity=21,
        wastage_basis=WastageBasis.ratti_of_received,
        wastage_ratti=Decimal("6"),
        wastage_ratti_base=96,
        wastage_allowed_pct=Decimal("0"),
        piece_count=0,
    )
    for key, value in overrides.items():
        setattr(leg, key, value)
    return leg


async def main():
    global ok, fail

    # ------------------------------------------------------- ratti arithmetic
    check(
        "six ratti of 96 on 107.560g allows 6.7225g",
        ratti_allowance(Decimal("107.560"), Decimal("6")) == Decimal("6.7225"),
        str(ratti_allowance(Decimal("107.560"), Decimal("6"))),
    )
    # The base travels on the leg because it is a convention, not a constant.
    check(
        "the base is honoured, not assumed",
        ratti_allowance(Decimal("96"), Decimal("6"), 100) == Decimal("5.7600"),
        str(ratti_allowance(Decimal("96"), Decimal("6"), 100)),
    )
    # An allowance of the whole base would settle every job square however much
    # metal went missing.
    check(
        "a ratti figure beyond the base is clamped, not trusted",
        ratti_allowance(Decimal("100"), Decimal("200"), 96) == Decimal("100.0000"),
        str(ratti_allowance(Decimal("100"), Decimal("200"), 96)),
    )
    check(
        "no ratti agreed allows nothing",
        ratti_allowance(Decimal("100"), Decimal("0")) == Decimal("0"),
    )

    # ------------------------------------------------------------- the bug
    # The reading that used to be taken: 21k credited at the purity that went
    # out. On this leg it hands the maker fourteen percent of a piece.
    overstated = fine_grams(Decimal("107.560"), 24)
    honest = fine_received_g(maker_leg())
    check(
        "107.560g of 21k is 94.115 fine grams, not 107.560",
        honest == Decimal("94.1150"),
        str(honest),
    )
    check(
        "valuing the return at the issued purity overstates it by about 14%",
        (overstated - honest) / honest > Decimal("0.14"),
        f"{overstated} vs {honest}",
    )

    # -------------------------------------------------------- the maker's job
    leg = maker_leg()
    settle_wastage(leg)
    check(
        "the allowance is worked out on the weight returned",
        d(leg.wastage_allowed_g) == Decimal("6.7225"),
        str(leg.wastage_allowed_g),
    )
    # 6.7225g of 21k, because the allowance is a slice of the jewellery he hands
    # back — not of the pure metal he was issued.
    check(
        "the allowance is converted at the purity it was measured against",
        d(leg.wastage_allowed_fine_g) == Decimal("5.8822"),
        str(leg.wastage_allowed_fine_g),
    )
    check(
        "the raw columns still say what the scale said",
        d(leg.wastage_actual_g) == Decimal("-7.5600"),
        str(leg.wastage_actual_g),
    )
    # The whole point. 100 fine out, 94.115 fine back, 5.8822 fine allowed —
    # the shop's own arithmetic said 99.997 against 100, and this is the same
    # residue seen from the other side.
    check(
        "the job is square: nothing recoverable from the maker",
        d(leg.wastage_excess_fine_g) < Decimal("0.01"),
        str(leg.wastage_excess_fine_g),
    )
    check(
        "and the shortfall in fine grams is the allowance, near enough",
        abs(d(leg.wastage_actual_fine_g) - d(leg.wastage_allowed_fine_g)) < Decimal("0.01"),
        f"{leg.wastage_actual_fine_g} vs {leg.wastage_allowed_fine_g}",
    )

    # A maker who returns less than the deal allows is short, and by a figure
    # the shop can put to him. 105g of 21k is 91.875 fine against 100 issued;
    # six ratti on 105 allows 6.5625g of 21k = 5.7422 fine.
    short = maker_leg(gold_received_g=Decimal("105"))
    settle_wastage(short)
    check(
        "a maker who returns less than his allowance is short by the difference",
        d(short.wastage_excess_fine_g) == Decimal("2.3828"),
        str(short.wastage_excess_fine_g),
    )

    # ------------------------------------------------- the other two bases
    # Unchanged, and asserted here because the fine-gram reckoning runs for all
    # three: a percentage leg where nothing was said about the return must
    # settle exactly as it did before any of this existed.
    pct = JobLeg(
        sequence=1,
        gold_issued_g=Decimal("100"),
        gold_issued_purity=22,
        gold_received_g=Decimal("98"),
        wastage_basis=WastageBasis.percent_of_issued,
        wastage_allowed_pct=Decimal("1.5"),
        piece_count=0,
    )
    settle_wastage(pct)
    check(
        "a percentage is still a percentage of what was issued",
        d(pct.wastage_allowed_g) == Decimal("1.5000"),
        str(pct.wastage_allowed_g),
    )
    check(
        "and its excess is the half gram beyond the allowance",
        d(pct.wastage_excess_g) == Decimal("0.5000"),
        str(pct.wastage_excess_g),
    )
    # Within a rounding step of the raw excess converted whole: the fine figures
    # are quantised at each end, so the two can differ in the fourth decimal.
    # What matters is that a silent leg still settles at one purity.
    check(
        "a leg silent about what came back reckons both ends at one purity",
        abs(d(pct.wastage_excess_fine_g) - fine_grams(Decimal("0.5"), 22)) <= Decimal("0.0001"),
        f"{pct.wastage_excess_fine_g} vs {fine_grams(Decimal('0.5'), 22)}",
    )

    setter = JobLeg(
        sequence=1,
        gold_issued_g=Decimal("106"),
        gold_issued_purity=24,
        gold_received_g=Decimal("102"),
        wastage_basis=WastageBasis.per_100_pieces,
        wastage_per_100_pcs_g=Decimal("0.400"),
        piece_count=350,
        wastage_allowed_pct=Decimal("0"),
    )
    settle_wastage(setter)
    check(
        "0.400g per 100 over 350 stones still allows 1.400g",
        d(setter.wastage_allowed_g) == Decimal("1.4000"),
        str(setter.wastage_allowed_g),
    )
    check(
        "and 2.600g is recoverable from the setter",
        d(setter.wastage_excess_g) == Decimal("2.6000"),
        str(setter.wastage_excess_g),
    )

    # ------------------------------------------------------------ the memo
    # A worker reads the charge and has to recognise the deal being invoked.
    check(
        "the charge names the maker's deal in ratti",
        agreed_terms(maker_leg()) == "6 ratti of 96 on the weight returned",
        agreed_terms(maker_leg()),
    )
    check(
        "and the setter's in grams per hundred",
        agreed_terms(setter) == "0.400g per 100 pieces agreed",
        agreed_terms(setter),
    )
    check("and the goldsmith's in percent", agreed_terms(pct) == "1.5% agreed", agreed_terms(pct))

    # ------------------------------------------------------------- the ledger
    async with SessionLocal() as db:
        department = (
            await db.execute(select(Department).where(Department.code == "MAKE"))
        ).unique().scalars().first()
        if department is None:
            print("\n[SKIP] the ledger checks need the Maker department")
            await db.rollback()
            print(f"\n{ok} passed, {fail} failed")
            raise SystemExit(1 if fail else 0)

        # A worker and an item are made here rather than looked for. The
        # postings under test are the same whether the shop has one karigar on
        # file or forty, and a test that quietly skips itself on a database
        # nobody has entered a worker into is a test that never runs.
        worker = (
            await db.execute(select(Vendor).where(Vendor.department_id == department.id).limit(1))
        ).unique().scalars().first()
        if worker is None:
            worker = Vendor(
                name="Smoke Maker", type=VendorType.karigar, department_id=department.id
            )
            db.add(worker)
        item = (await db.execute(select(Item).limit(1))).unique().scalars().first()
        if item is None:
            item = Item(name="Smoke Taka", abbreviation="SMK")
            db.add(item)
        await db.flush()

        # No department is put onto the new basis by the migration. The deal is
        # struck per job — wastage and the per-gram rate are independent
        # switches — so a default would force a ratti figure onto the maker's
        # every leg, including the ones where none was agreed.
        check(
            "no department is defaulted onto the ratti basis",
            department.default_wastage_basis != WastageBasis.ratti_of_received.value,
            department.default_wastage_basis,
        )

        design = Design(
            design_no="SMOKE-MAKER",
            item_id=item.id,
            status=DesignStatus.in_production,
        )
        db.add(design)
        await db.flush()

        rate = Decimal("21500")

        # --------------------------------------------- the maker's leg, posted
        posted = JobLeg(
            design_id=design.id,
            sequence=1,
            department_id=department.id,
            worker_id=worker.id,
            status=LegStatus.issued,
            metal=Metal.gold,
            gold_issued_g=Decimal("100"),
            gold_issued_purity=24,
            gold_received_g=Decimal("107.560"),
            gold_received_purity=21,
            wastage_basis=WastageBasis.ratti_of_received,
            wastage_ratti=Decimal("6"),
            wastage_ratti_base=96,
            wastage_allowed_pct=Decimal("0"),
            piece_count=0,
            labour_basis=LabourBasis.per_gram,
            labour_rate=Decimal("0"),
        )
        db.add(posted)
        await db.flush()
        await db.refresh(posted, ["department", "worker"])
        settle_wastage(posted)

        entry = await post_leg_receive(
            db, posted, design=design, worker=worker, rate=rate, user_id=None
        )
        lines = list(
            (await db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)))
            .scalars()
            .all()
        )

        in_hand = next(
            (l for l in lines if l.account.code == SystemAccount.GOLD_IN_HAND.value), None
        )
        check(
            "the metal booked into stock is the fine weight of the 21k that arrived",
            bool(in_hand and d(in_hand.quantity) == Decimal("94.1150")),
            str(in_hand.quantity if in_hand else None),
        )
        check(
            "and the line keeps the 21k the counter actually weighed",
            bool(in_hand and in_hand.native_purity == 21 and d(in_hand.native_weight_g) ==
                 Decimal("107.5600")),
            f"{in_hand.native_purity if in_hand else None} / "
            f"{in_hand.native_weight_g if in_hand else None}",
        )
        relief = next(
            (
                l
                for l in lines
                if l.account.code == SystemAccount.GOLD_WITH_WORKERS.value
                and d(l.quantity) < 0
            ),
            None,
        )
        check(
            "the maker is relieved of exactly the 100 fine grams he was issued",
            bool(relief and d(relief.quantity) == Decimal("-100.0000")),
            str(relief.quantity if relief else None),
        )
        # Not zero to the last decimal — the shop's own figures leave three
        # milligrams over, and the ledger reports what is there rather than
        # inventing a tolerance to swallow it. What matters is the order of
        # magnitude: milligrams, against the fourteen grams the old reading
        # would have charged him.
        recovered = next(
            (l for l in lines if l.account.code == SystemAccount.WASTAGE_RECOVERED.value), None
        )
        check(
            "the job is square: nothing beyond a few milligrams is charged back",
            recovered is None or abs(d(recovered.quantity)) < Decimal("0.01"),
            str(recovered.quantity if recovered else None),
        )

        # ------------------------------------------------------- on his gold
        # The same maker, working a piece on metal of his own. Nothing left the
        # safe; what arrives is his, and the shop owes it back.
        credit = JobLeg(
            design_id=design.id,
            sequence=2,
            department_id=department.id,
            worker_id=worker.id,
            status=LegStatus.issued,
            metal=Metal.gold,
            gold_issued_g=Decimal("0"),
            gold_received_g=Decimal("100"),
            gold_received_purity=21,
            metal_on_credit=True,
            wastage_basis=WastageBasis.percent_of_issued,
            wastage_allowed_pct=Decimal("0"),
            piece_count=0,
            labour_basis=LabourBasis.per_gram,
            labour_rate=Decimal("0"),
        )
        db.add(credit)
        await db.flush()
        await db.refresh(credit, ["department", "worker"])
        settle_wastage(credit)

        credit_entry = await post_leg_receive(
            db, credit, design=design, worker=worker, rate=rate, user_id=None
        )
        credit_lines = list(
            (await db.execute(select(JournalLine).where(JournalLine.entry_id == credit_entry.id)))
            .scalars()
            .all()
        )
        owed = next(
            (
                l
                for l in credit_lines
                if l.account.code == SystemAccount.GOLD_WITH_WORKERS.value
                and l.party_id == worker.id
            ),
            None,
        )
        check(
            "the worker's own metal is credited to him, not booked as free alloy",
            bool(owed and d(owed.quantity) == -fine_grams(Decimal("100"), 21)),
            str(owed.quantity if owed else None),
        )
        check(
            "his metal account swings negative — the shop is holding his gold",
            bool(owed and owed.party_type == PartyType.worker),
        )
        check(
            "and none of it lands in wastage, which would report a loss the shop never took",
            not any(
                l.account.code == SystemAccount.WASTAGE_EXPENSE.value for l in credit_lines
            ),
            str([l.account.code for l in credit_lines]),
        )

        await db.rollback()

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
