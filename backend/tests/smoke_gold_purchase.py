"""
Non-destructive smoke test for buying raw gold from a dealer.

The invariant under test is the one a purchase exists to protect: the metal and
the money move together, or neither moves. Everything runs inside a transaction
that is rolled back, so the developer's database is left as it was found.
"""
import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

logging.disable(logging.INFO)

from app.core.database import SessionLocal  # noqa: E402
from app.models.account import SystemAccount  # noqa: E402
from app.models.journal import Commodity, JournalLine  # noqa: E402
from app.models.purchase import (  # noqa: E402
    GoldPaymentMode,
    GoldPurchase,
    GoldPurchaseItem,
    Supplier,
)
from app.models.user import User  # noqa: E402
from app.services import branches as branch_svc  # noqa: E402
from app.services import purchasing as svc  # noqa: E402
from app.models.stock_movement import MovementType  # noqa: E402
from app.services.inventory import post_movement  # noqa: E402
from app.services.ledger import d, fine_grams  # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


async def lines_of(db, entry_id):
    return list(
        (await db.execute(select(JournalLine).where(JournalLine.entry_id == entry_id)))
        .scalars()
        .all()
    )


async def build(db, branch, supplier, *, mode, extra_pct="0"):
    """A two-lot bill: 100g of 24k and 50g of 22k."""
    purchase = GoldPurchase(
        purchase_no=await svc.next_gold_purchase_no(db),
        supplier_id=supplier.id,
        branch_id=branch.id,
        purchased_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        payment_mode=mode,
        subtotal=Decimal("0"),
        extra_cost_pct=Decimal(extra_pct),
        total=Decimal("0"),
    )
    db.add(purchase)
    await db.flush()

    rows = []
    subtotal = Decimal("0")
    for purity, weight, rate in ((24, "100", "30000"), (22, "50", "27500")):
        amount = svc.gold_line_amount(Decimal(weight), Decimal(rate))
        subtotal += amount
        pot = await svc.raw_gold_item(db, purity=purity, branch_id=branch.id)
        row = GoldPurchaseItem(
            purchase_id=purchase.id,
            purity=purity,
            weight_g=Decimal(weight),
            rate_per_g=Decimal(rate),
            amount=amount,
            inventory_item_id=pot.id,
        )
        db.add(row)
        rows.append(row)
        await db.flush()
        # The metal has to actually reach the pot, exactly as the endpoint puts
        # it there — otherwise a reversal has nothing to take back out and the
        # test would be exercising half a purchase.
        await post_movement(
            db,
            item=pot,
            type=MovementType.purchase_in,
            weight_g_delta=Decimal(weight),
            reference_type=svc.GOLD_PURCHASE_SOURCE,
            reference_id=purchase.id,
            notes=f"{purchase.purchase_no} smoke",
            user_id=None,
        )
    await db.flush()
    purchase.subtotal = subtotal
    purchase.total = svc.apply_extra_cost(subtotal, purchase.extra_cost_pct)
    await db.flush()
    return purchase, rows


async def main():
    async with SessionLocal() as db:
        admin = (await db.execute(select(User).limit(1))).scalars().first()
        branch = await branch_svc.default_branch(db)

        supplier = Supplier(name="ZZ Smoke Bullion", is_active=True)
        db.add(supplier)
        await db.flush()

        # --- numbering ---------------------------------------------------------
        no = await svc.next_gold_purchase_no(db)
        check("bill number minted in its own series", no.startswith("GP-"), no)
        check(
            "a dealer bill is not filed as a buy-back",
            not no.startswith("OG-"),
            "GP and OG have to be tellable apart by number alone",
        )

        # --- line maths --------------------------------------------------------
        check(
            "a lot is priced on its actual weight",
            svc.gold_line_amount(Decimal("100"), Decimal("30000")) == Decimal("3000000.00"),
            str(svc.gold_line_amount(Decimal("100"), Decimal("30000"))),
        )

        # --- cash purchase -----------------------------------------------------
        purchase, rows = await build(db, branch, supplier, mode=GoldPaymentMode.cash)
        check(
            "bill subtotal is the sum of its lots",
            d(purchase.subtotal) == Decimal("4375000.00"),
            str(purchase.subtotal),
        )
        entry = await svc.post_gold_purchase(
            db, purchase, rows, supplier_name=supplier.name, user_id=admin.id if admin else None
        )
        lines = await lines_of(db, entry.id)

        gold_lines = [ln for ln in lines if ln.commodity is Commodity.GOLD]
        check(
            "one gold line per lot, so the purity breakdown survives",
            len(gold_lines) == 2,
            f"got {len(gold_lines)}",
        )
        check(
            "metal is booked in fine grams, not gross",
            sum(d(ln.quantity) for ln in gold_lines)
            == fine_grams(Decimal("100"), 24) + fine_grams(Decimal("50"), 22),
            str(sum(d(ln.quantity) for ln in gold_lines)),
        )
        check(
            "each line keeps the weight and purity it arrived as",
            {(d(ln.native_weight_g), ln.native_purity) for ln in gold_lines}
            == {(Decimal("100.0000"), 24), (Decimal("50.0000"), 22)},
            str([(str(ln.native_weight_g), ln.native_purity) for ln in gold_lines]),
        )

        money = [ln for ln in lines if ln.commodity is not Commodity.GOLD]
        check("cash purchase credits one money line", len(money) == 1, f"got {len(money)}")
        check(
            "cash comes out of the till",
            money[0].account_id is not None
            and d(money[0].quantity) == -d(purchase.total),
            str(money[0].quantity),
        )
        check(
            "cash paid to a dealer is not tagged as the dealer's balance",
            money[0].party_id is None,
            f"party {money[0].party_id} — the till is the shop's own money, not a payable",
        )

        # --- credit purchase ---------------------------------------------------
        credit_purchase, credit_rows = await build(
            db, branch, supplier, mode=GoldPaymentMode.credit
        )
        credit_entry = await svc.post_gold_purchase(
            db, credit_purchase, credit_rows, supplier_name=supplier.name, user_id=None
        )
        credit_money = [
            ln for ln in await lines_of(db, credit_entry.id) if ln.commodity is not Commodity.GOLD
        ]
        check(
            "metal taken on account is a payable against that dealer",
            len(credit_money) == 1 and credit_money[0].party_id == supplier.id,
            f"party {credit_money[0].party_id if credit_money else None}",
        )

        # --- loading -----------------------------------------------------------
        loaded, loaded_rows = await build(
            db, branch, supplier, mode=GoldPaymentMode.cash, extra_pct="2"
        )
        check(
            "carriage is added on top of the metal",
            d(loaded.total) == Decimal("4462500.00"),
            str(loaded.total),
        )
        loaded_entry = await svc.post_gold_purchase(
            db, loaded, loaded_rows, supplier_name=supplier.name, user_id=None
        )
        loaded_lines = await lines_of(db, loaded_entry.id)
        gold_value = sum(
            d(ln.quantity) * d(ln.rate)
            for ln in loaded_lines
            if ln.commodity is Commodity.GOLD
        )
        check(
            "loading is capitalised into the metal, not expensed",
            abs(gold_value - d(loaded.total)) <= Decimal("0.01"),
            f"gold valued {gold_value} against a bill of {loaded.total}",
        )
        # The stored `value_pkr` is the ledger's own arithmetic, and netting to
        # zero on it is the invariant the whole double-entry system rests on.
        # Recomputing from the stored rate instead would be testing rounding,
        # not balance: the rate column holds 4dp while the value is exact.
        check(
            "the whole entry balances",
            sum(d(ln.value_pkr) for ln in loaded_lines) == Decimal("0"),
            str(sum(d(ln.value_pkr) for ln in loaded_lines)),
        )

        # --- refusals ----------------------------------------------------------
        from fastapi import HTTPException

        empty, empty_rows = await build(db, branch, supplier, mode=GoldPaymentMode.cash)
        empty.subtotal = Decimal("0")
        empty.total = Decimal("0")
        await db.flush()
        try:
            await svc.post_gold_purchase(
                db, empty, empty_rows, supplier_name=supplier.name, user_id=None
            )
            check("a bill of nothing is refused", False, "no error raised")
        except HTTPException:
            check("a bill of nothing is refused", True)

        never_posted = GoldPurchase(
            purchase_no=await svc.next_gold_purchase_no(db),
            supplier_id=supplier.id,
            branch_id=branch.id,
            purchased_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            payment_mode=GoldPaymentMode.cash,
        )
        db.add(never_posted)
        await db.flush()
        try:
            await svc.reverse_gold_purchase(db, never_posted, user_id=None)
            check("reversing an unposted bill is refused", False, "no error raised")
        except HTTPException:
            check("reversing an unposted bill is refused", True)

        # --- reversal ----------------------------------------------------------
        pot24 = await svc.raw_gold_item(db, purity=24, branch_id=branch.id)
        before = d(pot24.weight_g)
        # Flushed, not refreshed: a refresh would reload the row from the
        # database, where the id has not been written yet, and silently undo it.
        purchase.journal_entry_id = entry.id
        await db.flush()
        await svc.reverse_gold_purchase(db, purchase, user_id=None)
        await db.refresh(pot24)
        check(
            "reversing takes the metal back out of the safe",
            d(pot24.weight_g) == before - Decimal("100"),
            f"{before} -> {pot24.weight_g}",
        )
        try:
            await svc.reverse_gold_purchase(db, purchase, user_id=None)
            check("a bill cannot be reversed twice", False, "no error raised")
        except HTTPException:
            check("a bill cannot be reversed twice", True)

        await db.rollback()
        print("\n       rolled back — no changes committed")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
