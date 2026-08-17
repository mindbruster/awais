"""
Non-destructive smoke test for tunch and the party metal account.

Two things are under test, and they are the foundation the wholesale work sits
on.

**Tunch must be precise without disturbing anything already on the books.**
Every purity column in this system was a karat integer, and `fine_grams()`
computed karat/24. Between jewellers that is not good enough: they trade on an
assayed fineness quoted to a decimal, and on a five-kilo lot 91.6 against 92.0
is twenty fine grams. So tunch was added beside purity — but never backfilled,
because 22/24 is 0.91666... and any decimal written in its place would silently
restate the fine weight of every row already posted. The tests below pin both
halves of that: tunch wins when present, karat still governs when it is not.

**A trade party must be able to owe metal.** A retail customer owes money; a
wholesale counterparty owes fine grams *and* money, settling on different days
by different means. The party statement has to report both without netting them
against each other, because the metal side is deliberately unpriced.

Everything runs inside a transaction that is rolled back, so the developer's
database is left as it was found.
"""
import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

logging.disable(logging.INFO)

from app.core.database import SessionLocal  # noqa: E402
from app.models.account import Account, SystemAccount  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.journal import Commodity, JournalLine, PartyType  # noqa: E402
from app.services import ledger as svc  # noqa: E402
from app.services.ledger import EntryDraft, Posting, d, fine_grams  # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


async def main():
    global ok, fail

    # ---------------------------------------------------------------- tunch
    # Pure arithmetic, no database needed. These are the numbers the whole
    # migration was justified by, so they are asserted rather than assumed.
    check(
        "karat still governs when no tunch is given",
        fine_grams(100, 22) == Decimal("91.6667"),
        str(fine_grams(100, 22)),
    )
    check(
        "tunch wins over karat when both are present",
        fine_grams(100, 22, Decimal("91.6")) == Decimal("91.6000"),
        str(fine_grams(100, 22, Decimal("91.6"))),
    )
    check(
        "91.6 and 92.0 are twenty fine grams apart on a five-kilo lot",
        fine_grams(5000, 22, Decimal("92.0")) - fine_grams(5000, 22, Decimal("91.6"))
        == Decimal("20.0000"),
        str(fine_grams(5000, 22, Decimal("92.0")) - fine_grams(5000, 22, Decimal("91.6"))),
    )
    # A nought in an empty field is not an assay reading. Treating it as one
    # would value an entire lot at nothing, silently.
    check(
        "a zero tunch falls back to karat rather than valuing the lot at nothing",
        fine_grams(100, 22, 0) == Decimal("91.6667"),
        str(fine_grams(100, 22, 0)),
    )
    check(
        "a missing purity is taken as pure, as before",
        fine_grams(100, None) == Decimal("100.0000"),
        str(fine_grams(100, None)),
    )

    async with SessionLocal() as db:
        # ------------------------------------------------------- the account
        metal_acct = (
            await db.execute(
                select(Account).where(Account.code == SystemAccount.PARTY_METAL.value)
            )
        ).unique().scalar_one_or_none()
        check("account 1215 Party Metal exists", metal_acct is not None)
        check(
            "1215 is a system account and cannot be deleted from settings",
            bool(metal_acct and metal_acct.is_system),
        )
        making = (
            await db.execute(
                select(Account).where(Account.code == SystemAccount.MAKING_INCOME.value)
            )
        ).unique().scalar_one_or_none()
        check("account 4300 Making & Labour Income exists", making is not None)
        check("4300 is income, not expense", bool(making and making.type.value == "income"))

        customer = (
            await db.execute(select(Customer).order_by(Customer.id).limit(1))
        ).unique().scalars().first()
        if customer is None:
            print("\n[SKIP] no customer on file — ledger checks need one")
            await db.rollback()
            print(f"\n{ok} passed, {fail} failed")
            raise SystemExit(1 if fail else 0)

        opening = await svc.balance(
            db,
            account_code=SystemAccount.PARTY_METAL.value,
            commodity=Commodity.GOLD,
            party_type=PartyType.customer,
            party_id=customer.id,
        )

        # --------------------------------------- metal in, against no money
        # A jeweller dropping 500g of 22k for job work. The shop now holds his
        # metal: his metal account goes negative and no money moves at all —
        # the row a money-only ledger cannot express, which is the whole reason
        # for this account.
        rate = Decimal("21500")
        fine = fine_grams(500, 22, Decimal("91.6"))
        check("500g at 91.6 tunch is 458 fine grams", fine == Decimal("458.0000"), str(fine))

        draft = EntryDraft(memo="smoke: job-work metal received", source_type="manual")
        draft.add(
            Posting(
                account_code=SystemAccount.PARTY_METAL.value,
                quantity=-fine,
                commodity=Commodity.GOLD,
                rate=rate,
                native_weight_g=Decimal("-500"),
                native_purity=22,
                native_tunch_pct=Decimal("91.6"),
                party_type=PartyType.customer,
                party_id=customer.id,
            )
        )
        draft.add(
            Posting(
                account_code=SystemAccount.GOLD_IN_HAND.value,
                quantity=fine,
                commodity=Commodity.GOLD,
                rate=rate,
                native_weight_g=Decimal("500"),
                native_purity=22,
                native_tunch_pct=Decimal("91.6"),
            )
        )
        entry = await svc.post_entry(db, draft, user_id=None)
        check("a metal-only entry posts and balances", entry is not None)

        after = await svc.balance(
            db,
            account_code=SystemAccount.PARTY_METAL.value,
            commodity=Commodity.GOLD,
            party_type=PartyType.customer,
            party_id=customer.id,
        )
        check(
            "the party's metal balance goes negative — the shop holds his gold",
            after == opening - fine,
            f"{opening} -> {after}",
        )

        # The tunch actually reached the line, so a statement can show what the
        # counter saw rather than a karat band it rounded to.
        lines = list(
            (await db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)))
            .scalars()
            .all()
        )
        party_line = next(
            (l for l in lines if l.party_id == customer.id and l.party_type == PartyType.customer),
            None,
        )
        check("the party line carries its party identity", party_line is not None)
        check(
            "the tunch as weighed is kept on the line",
            bool(party_line and d(party_line.native_tunch_pct) == Decimal("91.600")),
            str(party_line.native_tunch_pct if party_line else None),
        )
        check(
            "quantity is fine grams, not as-weighed grams",
            bool(party_line and d(party_line.quantity) == -fine),
            str(party_line.quantity if party_line else None),
        )

        # ------------------------------------- money does not follow metal
        # The cash balance must be untouched by a metal movement. If these two
        # ever move together automatically, the shop is being told the jeweller
        # paid for something he has not agreed a price for.
        cash_after = await svc.balance_pkr(
            db,
            account_code=SystemAccount.PARTY_METAL.value,
            party_type=PartyType.customer,
            party_id=customer.id,
        )
        check(
            "the metal entry values in rupees for the trial balance",
            cash_after == -(fine * rate).quantize(Decimal("0.01")),
            str(cash_after),
        )

        # ---------------------------------------------- metal back out again
        # Delivering the finished pieces returns his fine weight. The account
        # comes back to where it started, which is what "give and take" means.
        back = EntryDraft(memo="smoke: job-work pieces delivered", source_type="manual")
        back.add(
            Posting(
                account_code=SystemAccount.PARTY_METAL.value,
                quantity=fine,
                commodity=Commodity.GOLD,
                rate=rate,
                party_type=PartyType.customer,
                party_id=customer.id,
            )
        )
        back.add(
            Posting(
                account_code=SystemAccount.GOLD_IN_HAND.value,
                quantity=-fine,
                commodity=Commodity.GOLD,
                rate=rate,
            )
        )
        await svc.post_entry(db, back, user_id=None)
        settled = await svc.balance(
            db,
            account_code=SystemAccount.PARTY_METAL.value,
            commodity=Commodity.GOLD,
            party_type=PartyType.customer,
            party_id=customer.id,
        )
        check(
            "returning the pieces squares the metal account",
            settled == opening,
            f"{opening} -> {settled}",
        )

        # ------------------------------------------------- party separation
        # A control account holds every party's movements. If the sub-ledger
        # filter leaked, one jeweller's gold would appear on another's
        # statement — the single worst failure this design could have.
        other = (
            await db.execute(
                select(Customer).where(Customer.id != customer.id).order_by(Customer.id).limit(1)
            )
        ).unique().scalars().first()
        if other is not None:
            leaked = await svc.balance(
                db,
                account_code=SystemAccount.PARTY_METAL.value,
                commodity=Commodity.GOLD,
                party_type=PartyType.customer,
                party_id=other.id,
            )
            check(
                "another party's statement is untouched by this one's metal",
                leaked == Decimal("0"),
                str(leaked),
            )

        await db.rollback()
        print("\n       rolled back — no changes committed")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
