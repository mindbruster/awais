"""
Do the shelves and the books agree?

Two records of the same metal exist, and they must never disagree:

  * `inventory_items.weight_g` — what the pots physically hold, updated by
    `post_movement`.
  * `1130 Gold in Hand` / `1135 Silver in Hand` — what the ledger says the shop
    owns, updated by `post_entry`.

Every legitimate path writes both in one transaction. A gap therefore means a
path exists that writes one and not the other — and that path is worth finding,
because a shop whose stock report and balance sheet disagree cannot tell which
one to believe.

This was written after finding exactly that: `PATCH /inventory/{id}` accepted a
`weight_g` and wrote it straight to the row, posting no movement and no entry.
On the development database it had left **1,195 fine grams** of gold in the pots
that the ledger had never seen — a net-worth figure that differed by a hundred
and twenty million rupees depending on which table it read.

**A tolerance of half a milligram, not zero.** Both sides are Decimal to four
places and the conversion to fine grams rounds at the same place, so a legitimate
pair can differ in the last digit. Anything larger is a real gap.

Run: `python -m tools.check_stock_ledger`   (or `npm run check:stock`)

Exits 0 when they agree, 1 when they do not.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import func, select

logging.disable(logging.INFO)

from app.core.database import SessionLocal  # noqa: E402
from app.models.account import Account, SystemAccount  # noqa: E402
from app.models.inventory import InventoryItem, InventoryType  # noqa: E402
from app.models.journal import Commodity, JournalEntry, JournalLine  # noqa: E402
from app.services import ledger  # noqa: E402
from app.services.ledger import fine_grams  # noqa: E402

# Rounding at four decimal places on both sides can legitimately differ in the
# last digit. Half a milligram is well inside that and nowhere near a real loss.
TOLERANCE = Decimal("0.0005")

CHECKS = (
    ("gold", InventoryType.raw_gold, SystemAccount.GOLD_IN_HAND, Commodity.GOLD),
    ("silver", InventoryType.raw_silver, SystemAccount.SILVER_IN_HAND, Commodity.SILVER),
)


async def main() -> int:
    bad = 0
    async with SessionLocal() as db:
        for label, inv_type, account, commodity in CHECKS:
            pots = (
                (await db.execute(select(InventoryItem).where(InventoryItem.type == inv_type)))
                .unique()
                .scalars()
                .all()
            )
            # Converted pot by pot, at each pot's own purity. Summing the raw
            # weights first and converting once would value a 22k pot at 24k.
            shelf = sum(
                (fine_grams(p.weight_g, p.purity, p.tunch_pct) for p in pots), Decimal("0")
            )
            books = await ledger.balance(
                db, account_code=account.value, commodity=commodity
            )
            # A manual voucher can move a metal account without touching a
            # pot, and that is legitimate: it is how an accountant corrects the
            # books, and demanding a stock movement would mean the ledger could
            # never be corrected at all. But it is a real divergence, so it is
            # named and subtracted rather than left to look like a mystery.
            hand_posted = Decimal(
                str(
                    (
                        await db.execute(
                            select(func.coalesce(func.sum(JournalLine.quantity), 0))
                            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                            .join(Account, Account.id == JournalLine.account_id)
                            .where(
                                Account.code == account.value,
                                JournalLine.commodity == commodity,
                                JournalEntry.source_type.in_(("manual", None)),
                            )
                        )
                    ).scalar_one()
                )
            ).quantize(Decimal("0.0001"))

            gap = (shelf - books).quantize(Decimal("0.0001"))
            unexplained = (gap + hand_posted).quantize(Decimal("0.0001"))

            if abs(unexplained) <= TOLERANCE:
                note = (
                    f"  ({hand_posted} fine g posted by hand, no stock behind it)"
                    if hand_posted
                    else ""
                )
                print(
                    f"  {label:<7} agree — {shelf} fine grams in {len(pots)} pot(s){note}"
                )
                continue

            bad += 1
            print(f"  {label:<7} DISAGREE")
            print(f"          shelves      {shelf} fine g  ({len(pots)} pots)")
            print(f"          books        {books} fine g  ({account.value})")
            print(f"          gap          {gap} fine g")
            if hand_posted:
                print(f"          by hand      {hand_posted} fine g  (manual vouchers)")
                print(f"          UNEXPLAINED  {unexplained} fine g")
            for p in pots:
                print(
                    f"            · {p.label}: {Decimal(str(p.weight_g or 0))} g"
                    f" at {p.purity or p.tunch_pct or '?'} →"
                    f" {fine_grams(p.weight_g, p.purity, p.tunch_pct)} fine"
                )

    if bad:
        print(
            "\nA gap means something moved stock without telling the books, or the\n"
            "reverse. Both are written in one transaction on every legitimate path,\n"
            "so look for a handler that sets a weight directly.\n\n"
            "To bring an existing shop into line, count the metal: /reconciliation\n"
            "posts the difference with a reason and a name on it."
        )
        return 1
    print("\nThe shelves and the books agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
