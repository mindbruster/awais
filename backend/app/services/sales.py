"""
What a sale does to the books, and what money does when it arrives.

Two events live here: issuing an invoice (the customer starts owing the shop)
and settling one (the customer stops). Both are business decisions that have to
give the same answer whoever asks — the API, a later import, the e2e suite — so
neither is allowed to be spelled out at a call site, and neither writes a
journal row directly: they build an `EntryDraft` and hand it to
`ledger.post_entry`, which is where the balancing invariant lives.

The rate convention is the one the rest of the system already uses: a gold rate
is **PKR per fine (24k-equivalent) gram**. `pricing.price_line` multiplies a
billable weight by `purity/24` before applying the invoice rate, so old gold
taken across the counter has to be converted the same way or a 22k exchange
would be paid for as though it were pure.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, case, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import SystemAccount
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import Commodity, JournalEntry, PartyType
from app.models.payment import Payment, PaymentDirection, PaymentMethod
from app.models.product import Product
from app.services.ledger import (
    EntryDraft,
    Posting,
    d,
    fine_grams,
    post_entry,
    reverse_entry,
)

# Entries are found again by this pair, which is how a void knows what to
# reverse and how a reversed payment stops counting against a balance.
INVOICE_SOURCE = "invoice"
PAYMENT_SOURCE = "payment"

_PKR = Decimal("0.01")

# Distinct from the keys serial.py and routing.py already hold, so minting a
# payment number never serialises against minting an invoice number.
_PAYMENT_LOCK_KEY = 7_300_007


async def next_payment_no(db: AsyncSession) -> str:
    """
    `PMT-YY-NNNNN`, same discipline as every other document number: advisory
    lock plus the highest suffix in use. Never a row count — reverse a payment
    (which keeps the row) or delete one and a count-based mint would hand out a
    number the unique index already holds.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_PAYMENT_LOCK_KEY))
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(Payment.payment_no, r"(\d+)$"), Integer)), 0
                )
            ).where(Payment.payment_no.like(f"PMT-{year}-%"))
        )
    ).scalar_one()
    return f"PMT-{year}-{int(highest) + 1:05d}"


def exchange_value(
    weight_g: Decimal, purity: int | None, rate_per_fine_g: Decimal
) -> tuple[Decimal, Decimal]:
    """
    Old gold across the counter, as (fine grams, rupees).

    The rupee figure is derived here rather than accepted from the caller so
    the payment row and the journal line can never disagree: the ledger values
    the same fine grams at the same rate, so `amount` is that product by
    construction instead of by hope.
    """
    fine = fine_grams(weight_g, purity)
    return fine, (fine * d(rate_per_fine_g)).quantize(_PKR)


def _require_pkr(invoice: Invoice) -> None:
    """
    The ledger holds rupees, and nothing in the shop declares an FX rate yet.

    A foreign-currency invoice posted as though its total were rupees would
    balance perfectly and be wrong by the exchange rate forever, so it is
    refused rather than guessed at — the same call `routing.current_gold_rate`
    makes about an unvalued gram.
    """
    if invoice.currency is not Currency.PKR:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{invoice.invoice_no} is a {invoice.currency.value} invoice and the books are "
            "kept in PKR. There is no FX rate on record to value it with, so it cannot be "
            "posted — raise it in PKR, or post the entry by hand at an agreed rate.",
        )


async def post_invoice_issued(
    db: AsyncSession, invoice: Invoice, *, user_id: int | None = None
) -> JournalEntry | None:
    """
    The customer now owes the shop, and the pieces leave the shelf.

    Two movements, one entry. Revenue: debit Customers, credit Sales for the
    invoice total. Cost: for every line carrying a stocked product, credit 1150
    Finished Goods by the metal that piece embodies and debit 5400 Cost of
    Goods Sold by its value. Without the second, 1150 only ever grows — stocking
    debits it and nothing relieves it — and within a month the books claim the
    shop is holding every piece it has ever sold.

    The metal is relieved in *fine* grams at the rate locked onto the product
    when it was stocked, so the credit is exactly the debit that put it there
    and a piece cannot leave the books worth more or less than it arrived.

    Returns None for a zero-value invoice — an entry with nothing on it is not
    a record of anything, and `post_entry` refuses empty drafts anyway.
    """
    _require_pkr(invoice)
    total = d(invoice.total).quantize(_PKR)
    if total == 0:
        return None

    draft = EntryDraft(
        memo=f"{invoice.invoice_no}: sale to customer #{invoice.customer_id}",
        source_type=INVOICE_SOURCE,
        source_id=invoice.id,
    )
    draft.add(
        Posting(
            account_code=SystemAccount.CUSTOMERS.value,
            quantity=total,
            party_type=PartyType.customer,
            party_id=invoice.customer_id,
            memo=f"Invoice {invoice.invoice_no}",
        )
    )
    draft.add(
        Posting(
            account_code=SystemAccount.SALES.value,
            quantity=-total,
            memo=f"Invoice {invoice.invoice_no}",
        )
    )

    for item in invoice.items:
        if item.product_id is None:
            continue
        product = await db.get(Product, item.product_id)
        # Only pieces that were actually stocked carry a locked rate. A line
        # against a product that never went through the stock form has nothing
        # sitting in 1150 to relieve, so relieving it would invent a balance.
        if product is None or product.gold_rate_at_cost is None:
            continue
        fine = fine_grams(product.gold_weight_g, product.gold_purity) * (item.quantity or 1)
        if fine <= 0:
            continue
        rate = d(product.gold_rate_at_cost)
        draft.add(
            Posting(
                account_code=SystemAccount.FINISHED_GOODS.value,
                quantity=-fine,
                commodity=Commodity.GOLD,
                rate=rate,
                native_weight_g=-d(product.gold_weight_g) * (item.quantity or 1),
                native_purity=product.gold_purity,
                memo=f"{product.serial_no} sold",
            )
        )
        draft.add(
            Posting(
                account_code=SystemAccount.COST_OF_GOODS_SOLD.value,
                quantity=(fine * rate).quantize(_PKR),
                memo=f"{product.serial_no} on {invoice.invoice_no}",
            )
        )

    return await post_entry(db, draft, user_id=user_id)


async def reverse_invoice_entries(
    db: AsyncSession, invoice: Invoice, *, user_id: int | None = None
) -> list[JournalEntry]:
    """
    Undo what issuing posted, by posting its mirror.

    A voided invoice is corrected, never erased: the original entry stays in
    the journal and a reversal points back at it, so the books can still
    explain how the receivable appeared and why it went away.
    """
    originals = (
        (
            await db.execute(
                select(JournalEntry)
                .where(
                    JournalEntry.source_type == INVOICE_SOURCE,
                    JournalEntry.source_id == invoice.id,
                    JournalEntry.reverses_entry_id.is_(None),
                )
                .order_by(JournalEntry.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        await reverse_entry(db, e, memo=f"Voided invoice {invoice.invoice_no}", user_id=user_id)
        for e in originals
    ]


def _asset_posting(payment: Payment, signed_amount: Decimal) -> Posting:
    """The side of the payment that is not the customer: what the shop received."""
    if payment.method is PaymentMethod.bank:
        return Posting(
            account_code=SystemAccount.BANK.value,
            quantity=signed_amount,
            memo=payment.reference or payment.payment_no,
        )
    if payment.method is PaymentMethod.gold_exchange:
        fine, _ = exchange_value(
            d(payment.gold_weight_g), payment.gold_purity, d(payment.gold_rate_per_g)
        )
        sign = Decimal("1") if signed_amount >= 0 else Decimal("-1")
        # Grams, not rupees. The metal is banked in fine grams and valued at the
        # rate agreed at the counter, which is snapshotted on the line so the
        # entry never moves when the market does.
        return Posting(
            account_code=SystemAccount.GOLD_IN_HAND.value,
            quantity=sign * fine,
            commodity=Commodity.GOLD,
            rate=d(payment.gold_rate_per_g),
            native_weight_g=sign * d(payment.gold_weight_g),
            native_purity=payment.gold_purity,
            memo=f"{d(payment.gold_weight_g)}g @ {payment.gold_purity or 24}k taken in exchange",
        )
    # cash, and advance — an advance is money in the till like any other; what
    # makes it an advance is that no invoice is attached to it yet.
    return Posting(
        account_code=SystemAccount.CASH_IN_HAND.value,
        quantity=signed_amount,
        memo=payment.reference or payment.payment_no,
    )


async def post_payment(
    db: AsyncSession,
    payment: Payment,
    *,
    customer: Customer,
    invoice: Invoice | None = None,
    user_id: int | None = None,
) -> JournalEntry:
    """
    Money or metal arrives, and the customer owes that much less.

    Whatever came across the counter is debited to the asset it became — cash
    to 1110, a transfer to 1120, old gold to 1130 in fine grams valued at the
    agreed rate — and Customers is credited for the party. `direction='paid'`
    is the exact mirror: the change handed back when a customer's old gold is
    worth more than the piece they are buying leaves the till and puts the
    balance back up.

    An advance posts identically with no invoice attached, which is what makes
    it show on the customer's statement as credit before a bill exists.
    """
    amount = d(payment.amount).quantize(_PKR)
    if amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A payment of nothing is not a payment — enter the amount taken.",
        )
    sign = Decimal("1") if payment.direction is PaymentDirection.received else Decimal("-1")
    signed = sign * amount

    where = f" against {invoice.invoice_no}" if invoice is not None else ""
    verb = "received from" if sign > 0 else "paid to"
    draft = EntryDraft(
        memo=f"{payment.payment_no}: {payment.method.value} {verb} {customer.name}{where}",
        source_type=PAYMENT_SOURCE,
        source_id=payment.id,
    )
    draft.add(_asset_posting(payment, signed))
    draft.add(
        Posting(
            account_code=SystemAccount.CUSTOMERS.value,
            quantity=-signed,
            party_type=PartyType.customer,
            party_id=payment.customer_id,
            memo=f"{payment.payment_no}{where}",
        )
    )
    return await post_entry(db, draft, user_id=user_id)


async def reverse_payment(
    db: AsyncSession, payment: Payment, *, user_id: int | None = None
) -> JournalEntry:
    """
    Cancel a payment by reversing its entry. The row stays.

    Deleting it would remove the evidence that money was taken and handed back,
    which is exactly what a customer disputing a receipt needs to see. Every
    balance derived from payments filters reversed ones out instead.
    """
    if payment.journal_entry_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{payment.payment_no} never posted to the ledger, so there is nothing to reverse.",
        )
    entry = await db.get(JournalEntry, payment.journal_entry_id)
    if entry is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{payment.payment_no} points at a journal entry that no longer exists.",
        )
    return await reverse_entry(
        db, entry, memo=f"Reversed payment {payment.payment_no}", user_id=user_id
    )


# --------------------------------------------------------------------------
# Derived figures. Nothing below is ever stored on a row.
# --------------------------------------------------------------------------
def _reversed_entry_ids():
    return select(JournalEntry.reverses_entry_id).where(
        JournalEntry.reverses_entry_id.is_not(None)
    )


def _live_only(stmt):
    """Narrow a payments query to the ones still standing."""
    return stmt.where(
        or_(
            Payment.journal_entry_id.is_(None),
            Payment.journal_entry_id.not_in(_reversed_entry_ids()),
        )
    )


async def reversed_payment_entry_ids(db: AsyncSession, entry_ids: list[int]) -> set[int]:
    """Which of these entries have been reversed — one query, not one per row."""
    if not entry_ids:
        return set()
    rows = (
        await db.execute(
            select(JournalEntry.reverses_entry_id).where(
                JournalEntry.reverses_entry_id.in_(entry_ids)
            )
        )
    ).scalars().all()
    return {r for r in rows if r is not None}


async def amount_paid(db: AsyncSession, invoice_id: int) -> Decimal:
    """
    What this invoice has actually been settled by, net of change given back.

    Derived from the payment rows every time rather than cached on the invoice:
    a stored figure would have to be maintained by every path that takes or
    reverses money, and the first one that forgets leaves a balance that cannot
    explain itself. Reversed payments are excluded, so cancelling a receipt
    puts the balance back without touching anything.

    Unapplied advances are deliberately not counted here — they are credit on
    the customer's account, not settlement of this bill, and applying them is a
    decision someone makes rather than one arithmetic performs.
    """
    signed = case(
        (Payment.direction == PaymentDirection.received, Payment.amount),
        else_=-Payment.amount,
    )
    stmt = _live_only(
        select(func.coalesce(func.sum(signed), 0)).where(Payment.invoice_id == invoice_id)
    )
    return d((await db.execute(stmt)).scalar_one()).quantize(_PKR)


async def settlement(db: AsyncSession, invoice: Invoice) -> tuple[Decimal, Decimal]:
    """
    (amount_paid, balance_due) for one invoice.

    Nothing is outstanding on a bill that was never raised or has been voided —
    a draft has not been presented to anyone and a void had its receivable
    reversed out of the ledger. Reporting the total as due in either state
    would put money on an ageing report that the books do not agree exists.
    """
    paid = await amount_paid(db, invoice.id)
    if invoice.status in (InvoiceStatus.draft, InvoiceStatus.void):
        return paid, Decimal("0.00")
    return paid, (d(invoice.total) - paid).quantize(_PKR)


async def refresh_status(db: AsyncSession, invoice: Invoice) -> tuple[Decimal, Decimal]:
    """
    Make the status follow the money instead of leading it.

    `paid` is a summary of the payment rows, not a flag someone sets: an
    invoice reads paid once nothing is outstanding, and falls back to issued
    the moment a payment behind it is reversed. Draft, void and returned are
    states of the *document* and are never touched from here.
    """
    paid, due = await settlement(db, invoice)
    if invoice.status is InvoiceStatus.issued and due <= 0:
        invoice.status = InvoiceStatus.paid
        invoice.paid_at = datetime.now(timezone.utc)
    elif invoice.status is InvoiceStatus.paid and due > 0:
        invoice.status = InvoiceStatus.issued
        invoice.paid_at = None
    return paid, due


async def live_payment_count(db: AsyncSession, invoice_id: int) -> int:
    """How many un-reversed payments are attached to this invoice."""
    stmt = _live_only(
        select(func.count(Payment.id)).where(Payment.invoice_id == invoice_id)
    )
    return int((await db.execute(stmt)).scalar_one())
