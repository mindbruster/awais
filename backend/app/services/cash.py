"""
The rest of a shop's money.

Everything else in this system moves cash as a consequence of a document: an
invoice bills, a payment settles, a purchase owes. What had nowhere to go was
the ordinary day — rent, wages, the electricity bill, a courier, tea, the owner
putting a few thousand into the till. None of it reached the books, so the cash
figure on the dashboard was only ever the part of the shop's money that happened
to pass through a sale, and the shop could not answer "where did today's money
go" from the system at all.

One entry, one balanced journal posting, and the cash and bank balances stay
derived from the ledger rather than from a column somebody has to remember.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, lock_keys
from app.models.account import Account, SystemAccount
from app.models.cash import CashDirection, CashEntry, CashMethod
from app.models.currency import Currency
from app.models.journal import JournalEntry
from app.services.ledger import EntryDraft, Posting, d, post_entry

SOURCE_TYPE = "cash_entry"

_PKR = Decimal("0.01")

# Where the money sits, by how it moved. Cash in the drawer and money in a bank
# account are different assets with different reconciliations — a drawer is
# counted, a bank account is agreed against a statement — so they are never one
# "cash" figure.
_SIDE_ACCOUNT = {
    CashMethod.cash: SystemAccount.CASH_IN_HAND,
    CashMethod.bank: SystemAccount.BANK,
}

# The head an entry falls to when its category names no account, or has no
# category at all. Honest rather than precise: better a rent payment sitting in
# Other Expenses than a rent payment nobody recorded because the chart of
# accounts was not set up first.
_DEFAULT_ACCOUNT = {
    CashDirection.paid: SystemAccount.OTHER_EXPENSES,
    CashDirection.received: SystemAccount.OTHER_INCOME,
}


async def next_entry_no(db: AsyncSession) -> str:
    """
    `CE-YY-NNNNN`, serialised by advisory lock.

    Derived from the highest suffix in use rather than a row count, so deleting
    an entry cannot cause its number to be handed out a second time.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.CASH_ENTRY_NO)
    )
    year = clock.today().strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(CashEntry.entry_no, r"(\d+)$"), Integer)), 0
                )
            ).where(CashEntry.entry_no.like(f"CE-{year}-%"))
        )
    ).scalar_one()
    return f"CE-{year}-{int(highest) + 1:05d}"


async def resolve_account(db: AsyncSession, entry: CashEntry) -> str:
    """
    Which head this entry posts against.

    The category's account when it names one and that account is real; the
    direction's default otherwise. A category pointing at an account that has
    since been deleted falls back rather than failing — the money moved either
    way, and refusing to record it because a chart entry was tidied away would
    lose the transaction to protect the filing.
    """
    code = entry.category.account_code if entry.category else None
    if code:
        exists = (
            await db.execute(select(Account.id).where(Account.code == code, Account.is_postable))
        ).scalar_one_or_none()
        if exists is not None:
            return code
    return _DEFAULT_ACCOUNT[entry.direction].value


async def post_cash_entry(
    db: AsyncSession, entry: CashEntry, *, user_id: int | None = None
) -> JournalEntry:
    """
    Two lines: the head it belongs to, and the drawer or account it moved through.

    Signs follow the ledger's convention — positive debits, negative credits.
    Money out debits an expense and credits cash; money in does the reverse.
    Both are valued in rupees, converting a foreign-currency entry at the rate
    on the row, because the cash book is kept in one currency or it cannot be
    added up.
    """
    code = await resolve_account(db, entry)
    side = _SIDE_ACCOUNT[entry.method].value
    amount = (d(entry.amount) * d(entry.fx_rate_to_pkr)).quantize(_PKR)
    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A cash entry has to move a positive amount. To reverse one, post the opposite "
            "entry rather than a negative — the books are append-only.",
        )

    outgoing = entry.direction is CashDirection.paid
    who = entry.counterparty or (entry.category.name if entry.category else "unspecified")
    where = (
        f"{entry.bank_account.bank.name} {entry.bank_account.account_no}"
        if entry.bank_account is not None and entry.bank_account.bank is not None
        else entry.method.value
    )
    draft = EntryDraft(
        memo=f"{entry.entry_no}: {'paid' if outgoing else 'received'} {amount} "
        f"{'to' if outgoing else 'from'} {who} by {where}",
        entry_date=entry.occurred_on,
        source_type=SOURCE_TYPE,
        source_id=entry.id,
    )
    draft.add(
        Posting(
            account_code=code,
            quantity=amount if outgoing else -amount,
            memo=entry.category.name if entry.category else None,
        )
    )
    draft.add(
        Posting(
            account_code=side,
            quantity=-amount if outgoing else amount,
            memo=where,
        )
    )
    return await post_entry(db, draft, user_id=user_id)


def validate_method(method: CashMethod, bank_account_id: int | None) -> None:
    """
    A bank movement names its account; a cash movement does not have one.

    Both halves matter. A bank figure with no account cannot be reconciled
    against a statement, which is the only reason to record it as a bank
    movement rather than as cash. And a cash movement carrying an account
    number says money passed through a bank that it never touched, which is
    worse than useless when the statement is being agreed.
    """
    if method is CashMethod.bank and bank_account_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A bank entry has to say which account the money moved through — without one "
            "it cannot be reconciled against a statement.",
        )
    if method is CashMethod.cash and bank_account_id is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This entry is marked as cash but names a bank account. Pick one: cash came out "
            "of the drawer, bank moved through the account.",
        )


def validate_currency(currency: Currency, fx_rate_to_pkr: Decimal) -> None:
    if currency is Currency.PKR and d(fx_rate_to_pkr) != Decimal("1"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "PKR is the book currency and converts to itself at 1.",
        )
