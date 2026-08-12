"""
Posting into the multi-commodity ledger.

Everything that moves money or metal goes through `post_entry`. It is the only
place journal rows are created, so the balancing invariant is enforced once
rather than trusted at every call site.

The invariant: an entry must net to exactly zero on `value_pkr`. Quantities
deliberately do *not* have to balance — a sale settled partly in old gold has
rupees on one side and grams on the other, and demanding per-commodity balance
would make that unpostable. Gold is valued at the rate agreed for that
transaction, which is snapshotted on the line so the entry never moves when the
market does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lock_keys
from app.models.account import Account, SystemAccount
from app.models.journal import Commodity, JournalEntry, JournalLine, PartyType

# Each line's PKR value is rounded to paisas independently, so a line can move
# by at most half a paisa. An entry of N lines can therefore drift by N * 0.005
# purely from rounding — three gold lines valued off the same rate routinely
# land a paisa apart. Anything inside that bound is rounding noise and gets
# absorbed; anything beyond it is a genuine imbalance and is refused.
_LINE_ROUNDING = Decimal("0.005")


def d(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


def fine_grams(weight_g: Decimal | float, purity: int | None) -> Decimal:
    """
    Convert an as-weighed amount to fine (24k-equivalent) grams.

    The ledger holds gold in fine grams so that 10g of 22k and 10g of 24k are
    not silently treated as the same asset. A missing purity is taken as pure,
    which matches how raw bullion is entered.
    """
    factor = d(purity) / Decimal("24") if purity else Decimal("1")
    return (d(weight_g) * factor).quantize(Decimal("0.0001"))


@dataclass
class Posting:
    """One side of an entry, before it becomes a JournalLine."""

    account_code: str
    # Signed: positive debits, negative credits.
    quantity: Decimal
    commodity: Commodity = Commodity.PKR
    # PKR per unit. Ignored for PKR (always 1).
    rate: Decimal = Decimal("1")
    party_type: PartyType | None = None
    party_id: int | None = None
    native_weight_g: Decimal | None = None
    native_purity: int | None = None
    memo: str | None = None

    def value_pkr(self) -> Decimal:
        if self.commodity is Commodity.PKR:
            return d(self.quantity).quantize(Decimal("0.01"))
        return (d(self.quantity) * d(self.rate)).quantize(Decimal("0.01"))


@dataclass
class EntryDraft:
    memo: str
    postings: list[Posting] = field(default_factory=list)
    entry_date: date | None = None
    source_type: str | None = None
    source_id: int | None = None

    def add(self, posting: Posting) -> "EntryDraft":
        self.postings.append(posting)
        return self


async def _account_by_code(db: AsyncSession, code: str) -> Account:
    account = (
        await db.execute(select(Account).where(Account.code == code))
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Chart of accounts is missing the system account '{code}'. "
            "Run the ledger seed before posting.",
        )
    if not account.is_postable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Account '{account.name}' is a heading and cannot be posted to directly.",
        )
    return account


async def next_entry_no(db: AsyncSession) -> str:
    """`JE-YY-NNNNN`, serialised by advisory lock and derived from the highest
    suffix in use so a deleted row can never cause a collision."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.JOURNAL_ENTRY_NO))
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(JournalEntry.entry_no, r"(\d+)$"), Integer)),
                    0,
                )
            ).where(JournalEntry.entry_no.like(f"JE-{year}-%"))
        )
    ).scalar_one()
    return f"JE-{year}-{int(highest) + 1:05d}"


async def post_entry(
    db: AsyncSession,
    draft: EntryDraft,
    *,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Validate and persist one balanced entry. The caller commits.

    Raises 400 when the postings don't net to zero — that is a programming
    error in whichever service built the draft, and letting it through would
    corrupt every balance derived from the ledger afterwards.
    """
    if not draft.postings:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Refusing to post an entry with no lines.")

    values = [p.value_pkr() for p in draft.postings]
    total = sum(values, Decimal("0"))
    tolerance = _LINE_ROUNDING * len(values)

    if abs(total) > tolerance:
        detail = " | ".join(
            f"{p.account_code}:{p.commodity.value} {v}"
            for p, v in zip(draft.postings, values)
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Entry does not balance — debits minus credits = {total} PKR. Lines: {detail}",
        )

    # Absorb the residual rather than storing it. Tolerating a paisa here would
    # leave it in the books forever, and the trial balance — which compares
    # stored values exactly — would report the whole ledger as unbalanced. The
    # largest line takes the correction, where it distorts least.
    if total != 0:
        biggest = max(range(len(values)), key=lambda i: abs(values[i]))
        values[biggest] -= total

    entry = JournalEntry(
        entry_no=await next_entry_no(db),
        entry_date=draft.entry_date or datetime.now(timezone.utc).date(),
        memo=draft.memo,
        source_type=draft.source_type,
        source_id=draft.source_id,
        posted_at=datetime.now(timezone.utc),
        created_by_user_id=user_id,
    )
    db.add(entry)
    await db.flush()

    for p, value in zip(draft.postings, values):
        account = await _account_by_code(db, p.account_code)
        db.add(
            JournalLine(
                entry_id=entry.id,
                account_id=account.id,
                commodity=p.commodity,
                quantity=d(p.quantity).quantize(Decimal("0.0001")),
                rate=d(p.rate).quantize(Decimal("0.0001")),
                value_pkr=value,
                native_weight_g=p.native_weight_g,
                native_purity=p.native_purity,
                party_type=p.party_type,
                party_id=p.party_id,
                memo=p.memo,
            )
        )
    await db.flush()
    return entry


async def reverse_entry(
    db: AsyncSession,
    entry: JournalEntry,
    *,
    memo: str,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Post the mirror image of an entry.

    Corrections are always new entries, never edits. An edited ledger cannot
    explain how it reached a balance, which defeats the reason for keeping one.
    """
    if entry.reverses_entry_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Refusing to reverse a reversal; reverse the original."
        )
    existing = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.reverses_entry_id == entry.id)
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Entry {entry.entry_no} was already reversed by {existing.entry_no}.",
        )

    reversal = JournalEntry(
        entry_no=await next_entry_no(db),
        entry_date=datetime.now(timezone.utc).date(),
        memo=memo,
        source_type=entry.source_type,
        source_id=entry.source_id,
        reverses_entry_id=entry.id,
        posted_at=datetime.now(timezone.utc),
        created_by_user_id=user_id,
    )
    db.add(reversal)
    await db.flush()

    for line in entry.lines:
        db.add(
            JournalLine(
                entry_id=reversal.id,
                account_id=line.account_id,
                commodity=line.commodity,
                quantity=-d(line.quantity),
                rate=line.rate,
                value_pkr=-d(line.value_pkr),
                native_weight_g=line.native_weight_g,
                native_purity=line.native_purity,
                party_type=line.party_type,
                party_id=line.party_id,
                memo=f"Reversal of {entry.entry_no}",
            )
        )
    await db.flush()
    return reversal


async def balance(
    db: AsyncSession,
    *,
    account_code: str | None = None,
    commodity: Commodity = Commodity.PKR,
    party_type: PartyType | None = None,
    party_id: int | None = None,
    up_to: date | None = None,
) -> Decimal:
    """
    Signed balance in the commodity's own unit — rupees, dollars, or fine grams.

    Positive is a debit balance (an asset, or money owed to the shop); negative
    is a credit balance. Reconstructed from lines every time rather than cached
    on a row, so it can always explain itself and can never drift.
    """
    stmt = select(func.coalesce(func.sum(JournalLine.quantity), 0)).where(
        JournalLine.commodity == commodity
    )
    if account_code:
        stmt = stmt.join(Account, Account.id == JournalLine.account_id).where(
            Account.code == account_code
        )
    if party_type is not None:
        stmt = stmt.where(JournalLine.party_type == party_type)
    if party_id is not None:
        stmt = stmt.where(JournalLine.party_id == party_id)
    if up_to is not None:
        stmt = stmt.join(
            JournalEntry, JournalEntry.id == JournalLine.entry_id
        ).where(JournalEntry.entry_date <= up_to)
    return d((await db.execute(stmt)).scalar_one())


async def balance_pkr(
    db: AsyncSession,
    *,
    account_code: str | None = None,
    party_type: PartyType | None = None,
    party_id: int | None = None,
    up_to: date | None = None,
) -> Decimal:
    """
    Signed balance in rupees, across every commodity on the account.

    `balance` answers "how many of this unit", which is the only sensible
    question for metal — grams and dollars cannot be added. A headline money
    figure is the other question, and asking it through `balance` is a trap: a
    dollar bill settled in rupees posts the debit as USD and the credit as PKR,
    so summing one commodity keeps the payment and drops the invoice. The
    account then reads as a large negative — the shop appears to owe its
    customers a million rupees — while the ledger underneath is perfectly
    correct and balanced.

    Every line already carries `value_pkr`, converted at the rate in force when
    it was written. Summing that is what turns a mixed-currency account back
    into one number, and it stays stable afterwards because those rates were
    snapshotted rather than re-read.
    """
    stmt = select(func.coalesce(func.sum(JournalLine.value_pkr), 0))
    if account_code:
        stmt = stmt.join(Account, Account.id == JournalLine.account_id).where(
            Account.code == account_code
        )
    if party_type is not None:
        stmt = stmt.where(JournalLine.party_type == party_type)
    if party_id is not None:
        stmt = stmt.where(JournalLine.party_id == party_id)
    if up_to is not None:
        stmt = stmt.join(
            JournalEntry, JournalEntry.id == JournalLine.entry_id
        ).where(JournalEntry.entry_date <= up_to)
    return d((await db.execute(stmt)).scalar_one())


async def worker_gold_balance(db: AsyncSession, worker_id: int) -> Decimal:
    """Fine grams of shop metal this worker is holding or owes."""
    return await balance(
        db,
        account_code=SystemAccount.GOLD_WITH_WORKERS.value,
        commodity=Commodity.GOLD,
        party_type=PartyType.worker,
        party_id=worker_id,
    )


async def customer_balance(db: AsyncSession, customer_id: int) -> Decimal:
    """
    Rupees this customer owes the shop. Negative means they're in credit.

    Valued rather than per-commodity: a customer billed in dollars and paying
    in rupees has legs on both sides of the account, and counting only the
    rupee ones shows a paid-up customer as heavily in credit.
    """
    return await balance_pkr(
        db,
        account_code=SystemAccount.CUSTOMERS.value,
        party_type=PartyType.customer,
        party_id=customer_id,
    )
