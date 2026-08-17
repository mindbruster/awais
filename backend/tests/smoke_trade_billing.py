"""
Non-destructive smoke test for bills that charge gold in grams.

The shop writes two kinds of invoice. At the counter the gold is priced and the
customer settles one rupee figure. With another jeweller the metal is never
priced: the bill states the fine grams to hand over, and cash is owed only for
the stones and the making.

The failure this guards against is the expensive one — billing the same gold
twice. If a trade bill both told the jeweller to hand over 9.166 fine grams and
charged him rupees for that same metal, he would be invoiced for it in two
units at once, and neither side would notice until settlement.

So the tests below pin the two documents against each other on identical
figures, and then check the ledger agrees with whichever one was printed.

Everything runs inside a transaction that is rolled back, so the developer's
database is left as it was found.
"""
import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

logging.disable(logging.INFO)

from app.api.v1.invoices import _recompute  # noqa: E402
from app.core import clock  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.account import Account, SystemAccount  # noqa: E402
from app.models.branch import Branch  # noqa: E402
from app.models.currency import Currency  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.gold_rate import GoldRate  # noqa: E402
from app.models.invoice import (  # noqa: E402
    GoldCharge,
    Invoice,
    InvoiceItem,
    InvoiceStatus,
)
from app.models.journal import Commodity, JournalLine, PartyType  # noqa: E402
from app.services import ledger as ledger_svc  # noqa: E402
from app.services import sales as sales_svc  # noqa: E402
from app.services.ledger import d  # noqa: E402

ok = fail = 0
RATE = Decimal("21500")


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


def build(customer, branch, *, charged_in):
    """
    The same piece, billed both ways: 10 g of 22k, a half-carat stone at
    80,000, and 5,000 of making.
    """
    inv = Invoice(
        invoice_no=f"SMOKE-{charged_in.value}",
        branch_id=branch.id,
        customer_id=customer.id,
        currency=Currency.PKR,
        status=InvoiceStatus.draft,
        gold_rate_per_g=RATE,
        gold_charged_in=charged_in,
        issued_at=clock.now(),
        # Set explicitly: column defaults are applied by the database on flush,
        # and this row is priced before it is ever written. The real create path
        # fills them from the request payload.
        discount_amount=Decimal("0"),
        discount_weight_g=Decimal("0"),
        tax_amount=Decimal("0"),
        round_off=Decimal("0"),
        term_days=0,
    )
    inv.items = [
        InvoiceItem(
            description="Ring",
            quantity=1,
            gold_weight_g=Decimal("10"),
            gold_purity=22,
            stone_weight_ct=Decimal("0.5"),
            stone_rate_per_ct=Decimal("80000"),
            labor_amount=Decimal("5000"),
        )
    ]
    _recompute(inv)
    return inv


async def lines_of(db, entry_id):
    return list(
        (await db.execute(select(JournalLine).where(JournalLine.entry_id == entry_id)))
        .scalars()
        .all()
    )


async def main():
    global ok, fail

    async with SessionLocal() as db:
        branch = (
            await db.execute(select(Branch).order_by(Branch.id).limit(1))
        ).unique().scalars().first()
        customer = (
            await db.execute(select(Customer).order_by(Customer.id).limit(1))
        ).unique().scalars().first()
        if branch is None or customer is None:
            print("\n[SKIP] a branch and a customer are needed")
            raise SystemExit(0)

        # The books must be able to value metal even though the bill does not
        # price it, so a rate has to be on record.
        today = clock.today()
        existing = (
            await db.execute(
                select(GoldRate).where(
                    GoldRate.currency == Currency.PKR,
                    GoldRate.purity == 24,
                    GoldRate.rate_date <= today,
                )
            )
        ).scalars().first()
        if existing is None:
            db.add(GoldRate(currency=Currency.PKR, purity=24, rate_date=today, rate_per_g=RATE))
            await db.flush()

        # ------------------------------------------------ the counter bill
        counter = build(customer, branch, charged_in=GoldCharge.rupees)
        check(
            "a counter bill prices the gold",
            d(counter.items[0].gold_amount) == Decimal("197083.33"),
            str(counter.items[0].gold_amount),
        )
        check(
            "a counter bill's total is gold + stones + making",
            d(counter.total) == Decimal("242083.33"),
            str(counter.total),
        )
        check(
            "a counter bill has no metal obligation",
            d(counter.metal_due_fine_g) == 0,
            str(counter.metal_due_fine_g),
        )

        # -------------------------------------------------- the trade bill
        trade = build(customer, branch, charged_in=GoldCharge.grams)
        check(
            "a trade bill does not price the gold at all",
            d(trade.items[0].gold_amount) == 0,
            str(trade.items[0].gold_amount),
        )
        check(
            "a trade bill's cash total is stones + making only",
            d(trade.total) == Decimal("45000.00"),
            str(trade.total),
        )
        check(
            "a trade bill states the fine grams to hand over",
            d(trade.metal_due_fine_g) == Decimal("9.1667"),
            str(trade.metal_due_fine_g),
        )
        # The whole point: the gold appears in exactly one unit, never both.
        check(
            "the same gold is never billed in rupees and in grams at once",
            (d(trade.metal_due_fine_g) > 0) and (d(trade.items[0].gold_amount) == 0),
        )
        check(
            "the two bills differ by exactly the priced gold",
            d(counter.total) - d(trade.total) == Decimal("197083.33"),
            f"{counter.total} - {trade.total}",
        )

        # Tunch beats karat on the metal side too, so the bill and the ledger
        # agree about how pure the gold was.
        tunched = build(customer, branch, charged_in=GoldCharge.grams)
        tunched.items[0].gold_tunch_pct = Decimal("91.6")
        _recompute(tunched)
        check(
            "the fine weight follows the tunch when one is given",
            d(tunched.metal_due_fine_g) == Decimal("9.1600"),
            str(tunched.metal_due_fine_g),
        )

        # ------------------------------------------------------ the posting
        opening_metal = await ledger_svc.balance(
            db,
            account_code=SystemAccount.PARTY_METAL.value,
            commodity=Commodity.GOLD,
            party_type=PartyType.customer,
            party_id=customer.id,
        )

        db.add(trade)
        await db.flush()
        entry = await sales_svc.post_invoice_issued(db, trade, user_id=None)
        check("issuing a trade bill posts an entry", entry is not None)

        lines = await lines_of(db, entry.id)
        check(
            "the entry balances to zero in rupees",
            sum((d(l.value_pkr) for l in lines), Decimal("0")) == 0,
            str(sum((d(l.value_pkr) for l in lines), Decimal("0"))),
        )

        by_code: dict[str, list[JournalLine]] = {}
        for line in lines:
            acct = await db.get(Account, line.account_id)
            by_code.setdefault(acct.code, []).append(line)

        metal_lines = by_code.get(SystemAccount.PARTY_METAL.value, [])
        check("the metal lands on the party metal account", len(metal_lines) == 1)
        check(
            "the metal line is in fine grams, against this party",
            bool(
                metal_lines
                and d(metal_lines[0].quantity) == Decimal("9.1667")
                and metal_lines[0].commodity is Commodity.GOLD
                and metal_lines[0].party_id == customer.id
            ),
            str(metal_lines[0].quantity if metal_lines else None),
        )

        cash_lines = by_code.get(SystemAccount.CUSTOMERS.value, [])
        check(
            "only the cash side lands on the customer receivable",
            bool(cash_lines and d(cash_lines[0].quantity) == Decimal("45000.00")),
            str(cash_lines[0].quantity if cash_lines else None),
        )

        making = by_code.get(SystemAccount.MAKING_INCOME.value, [])
        check(
            "making is credited to its own income account, not to Sales",
            bool(making and d(making[0].quantity) == Decimal("-5000.00")),
            str(making[0].quantity if making else None),
        )
        sales_lines = by_code.get(SystemAccount.SALES.value, [])
        check(
            "Sales carries the metal and the stones, less the making",
            bool(sales_lines and d(sales_lines[0].quantity) < 0),
            str(sales_lines[0].quantity if sales_lines else None),
        )

        after = await ledger_svc.balance(
            db,
            account_code=SystemAccount.PARTY_METAL.value,
            commodity=Commodity.GOLD,
            party_type=PartyType.customer,
            party_id=customer.id,
        )
        check(
            "the jeweller now owes the shop metal",
            after == opening_metal + Decimal("9.1667"),
            f"{opening_metal} -> {after}",
        )

        # ------------------------------------------------------- the void
        # A cancelled bill must give the metal back. If a reversal only undid
        # the money, the shop would go on believing it was owed gold that was
        # never actually sold.
        await sales_svc.reverse_invoice_entries(db, trade, user_id=None)
        settled = await ledger_svc.balance(
            db,
            account_code=SystemAccount.PARTY_METAL.value,
            commodity=Commodity.GOLD,
            party_type=PartyType.customer,
            party_id=customer.id,
        )
        check(
            "voiding the bill takes the metal obligation back off",
            settled == opening_metal,
            f"{opening_metal} -> {settled}",
        )

        await db.rollback()
        print("\n       rolled back — no changes committed")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
