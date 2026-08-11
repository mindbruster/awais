"""
Taking money at the counter.

A payment is a settlement against an invoice, or an advance held before one
exists. Every row posts a balanced journal entry through
`app.services.sales.post_payment` — nothing here writes journal rows directly —
so a customer's balance is derived from the books rather than trusted to a
status flag, which is what the old `mark-paid` did and why nobody could chase
an outstanding amount.

Payments are never deleted. A mistake is corrected by reversing the entry,
which leaves the receipt and its cancellation both visible.
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.bank import BankAccount
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.payment import Payment, PaymentDirection, PaymentMethod
from app.models.stock_movement import MovementType
from app.schemas.payment import PaymentCreate, PaymentRead, PaymentReverseRequest
from app.services import purchasing, sales
from app.services.audit import log_action
from app.services.inventory import post_movement
from app.services.ledger import d

router = APIRouter()
read = Depends(require_perm("payment:read"))
write = Depends(require_perm("payment:write"))
reverse = Depends(require_perm("payment:reverse"))
confirm = Depends(require_password_confirm)


def payment_read(
    payment: Payment,
    *,
    customer: Customer | None = None,
    invoice: Invoice | None = None,
    entry_no: str | None = None,
    is_reversed: bool = False,
) -> PaymentRead:
    fine = None
    if payment.method is PaymentMethod.gold_exchange and payment.gold_weight_g is not None:
        fine, _ = sales.exchange_value(
            d(payment.gold_weight_g), payment.gold_purity, d(payment.gold_rate_per_g)
        )
    ba = payment.bank_account
    return PaymentRead(
        id=payment.id,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        payment_no=payment.payment_no,
        invoice_id=payment.invoice_id,
        invoice_no=invoice.invoice_no if invoice else None,
        customer_id=payment.customer_id,
        customer_name=customer.name if customer else None,
        method=payment.method,
        direction=payment.direction,
        amount=d(payment.amount),
        gold_weight_g=payment.gold_weight_g,
        gold_purity=payment.gold_purity,
        gold_rate_per_g=payment.gold_rate_per_g,
        gold_fine_g=fine,
        bank_account_id=payment.bank_account_id,
        bank_account_label=(
            f"{ba.bank.name} · {ba.account_no}" if ba and ba.bank else (ba.account_no if ba else None)
        ),
        paid_at=payment.paid_at,
        reference=payment.reference,
        notes=payment.notes,
        journal_entry_id=payment.journal_entry_id,
        entry_no=entry_no,
        is_reversed=is_reversed,
    )


async def decorate_payments(db: DbSession, payments: list[Payment]) -> list[PaymentRead]:
    """
    Fill in the names, entry numbers and reversal flags in bulk.

    A payments list is read at the counter while a customer waits, so the
    lookups it needs are three queries for the whole page rather than three per
    row.
    """
    if not payments:
        return []
    customer_ids = {p.customer_id for p in payments}
    invoice_ids = {p.invoice_id for p in payments if p.invoice_id}
    entry_ids = [p.journal_entry_id for p in payments if p.journal_entry_id]

    customers = {
        c.id: c
        for c in (
            (await db.execute(select(Customer).where(Customer.id.in_(customer_ids))))
            .unique()
            .scalars()
            .all()
        )
    }
    invoices = (
        {
            i.id: i
            for i in (
                (await db.execute(select(Invoice).where(Invoice.id.in_(invoice_ids))))
                .unique()
                .scalars()
                .all()
            )
        }
        if invoice_ids
        else {}
    )
    entries = (
        {
            e.id: e
            for e in (
                (await db.execute(select(JournalEntry).where(JournalEntry.id.in_(entry_ids))))
                .unique()
                .scalars()
                .all()
            )
        }
        if entry_ids
        else {}
    )
    reversed_ids = await sales.reversed_payment_entry_ids(db, entry_ids)

    return [
        payment_read(
            p,
            customer=customers.get(p.customer_id),
            invoice=invoices.get(p.invoice_id) if p.invoice_id else None,
            entry_no=entries[p.journal_entry_id].entry_no if p.journal_entry_id in entries else None,
            is_reversed=p.journal_entry_id in reversed_ids,
        )
        for p in payments
    ]


async def _load(db: DbSession, payment_id: int) -> Payment:
    payment = (
        await db.execute(
            select(Payment)
            .where(Payment.id == payment_id)
            .execution_options(populate_existing=True)
        )
    ).unique().scalar_one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return payment


@router.get("", response_model=list[PaymentRead], dependencies=[read])
async def list_payments(
    db: DbSession,
    invoice_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    method: PaymentMethod | None = Query(default=None),
    direction: PaymentDirection | None = Query(default=None),
    unapplied: bool | None = Query(
        default=None, description="True for advances not yet attached to an invoice"
    ),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PaymentRead]:
    stmt = (
        select(Payment)
        .order_by(desc(Payment.paid_at), desc(Payment.id))
        .limit(limit)
        .offset(offset)
    )
    if invoice_id is not None:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    if customer_id is not None:
        stmt = stmt.where(Payment.customer_id == customer_id)
    if method is not None:
        stmt = stmt.where(Payment.method == method)
    if direction is not None:
        stmt = stmt.where(Payment.direction == direction)
    if unapplied is True:
        stmt = stmt.where(Payment.invoice_id.is_(None))
    elif unapplied is False:
        stmt = stmt.where(Payment.invoice_id.is_not(None))
    return await decorate_payments(db, list((await db.execute(stmt)).unique().scalars().all()))


@router.post(
    "", response_model=PaymentRead, status_code=status.HTTP_201_CREATED, dependencies=[write]
)
async def create_payment(
    payload: PaymentCreate, db: DbSession, current: CurrentUser
) -> PaymentRead:
    """
    Record money or metal taken, and post it to the books in the same
    transaction — a receipt the ledger never heard about is the hole this
    replaces.
    """
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid customer_id")

    invoice: Invoice | None = None
    if payload.invoice_id is not None:
        invoice = await db.get(Invoice, payload.invoice_id)
        if invoice is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid invoice_id")
        if invoice.customer_id != customer.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{invoice.invoice_no} belongs to a different customer. Take the money "
                "against their own bill, or record it as an advance.",
            )
        if invoice.status in (InvoiceStatus.draft, InvoiceStatus.void):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{invoice.invoice_no} is {invoice.status.value} — there is nothing owed on it "
                "yet. Issue it first, or take the money as an advance.",
            )

    if payload.bank_account_id is not None:
        if await db.get(BankAccount, payload.bank_account_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid bank_account_id")

    amount = payload.amount
    if payload.method is PaymentMethod.gold_exchange:
        # Derived, never taken from the caller: the ledger values the same fine
        # grams at the same rate, so the receipt cannot say one thing and the
        # journal another.
        _, amount = sales.exchange_value(
            payload.gold_weight_g, payload.gold_purity, payload.gold_rate_per_g
        )

    # A settlement cannot exceed what is owed. Left unchecked, `balance_due`
    # goes negative and the invoice reads as though the shop owes the customer,
    # which is a different transaction with a different answer: money handed
    # back is `direction=paid`, and money taken with no bill behind it is an
    # advance. Both are recordable — this just refuses to disguise one as the
    # other. Gold exchange is the common way in: metal worth more than the piece
    # is exactly the case the reference product pays out in cash.
    if (
        invoice is not None
        and payload.direction is PaymentDirection.received
        and amount > 0
    ):
        _, outstanding = await sales.settlement(db, invoice)
        if amount > outstanding:
            over = (amount - outstanding).quantize(Decimal("0.01"))
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"That is {over} more than the {outstanding} still owed on "
                f"{invoice.invoice_no}. Take the balance against the bill and the rest as an "
                "advance, or pay the difference back with direction=paid.",
            )

    payment = Payment(
        payment_no=await sales.next_payment_no(db),
        invoice_id=payload.invoice_id,
        customer_id=payload.customer_id,
        method=payload.method,
        direction=payload.direction,
        amount=amount,
        gold_weight_g=payload.gold_weight_g,
        gold_purity=payload.gold_purity,
        gold_rate_per_g=payload.gold_rate_per_g,
        bank_account_id=payload.bank_account_id,
        paid_at=payload.paid_at or datetime.now(timezone.utc),
        reference=payload.reference,
        notes=payload.notes,
        created_by_user_id=current.id,
    )
    db.add(payment)
    # The entry carries the payment's id as its source, so the row has to exist
    # before it can be posted against.
    await db.flush()

    entry = await sales.post_payment(
        db, payment, customer=customer, invoice=invoice, user_id=current.id
    )
    payment.journal_entry_id = entry.id

    # Metal taken across the counter has to land in the melt pot as well as in
    # the ledger. Posting only the journal entry leaves 1130 Gold in Hand and
    # the raw-gold stock disagreeing by the weight of every exchange ever
    # taken — and the two are supposed to be the same metal counted two ways.
    if payment.method is PaymentMethod.gold_exchange:
        pot = await purchasing.raw_gold_item(db, purity=int(payment.gold_purity))
        weight = Decimal(str(payment.gold_weight_g))
        await post_movement(
            db,
            item=pot,
            type=(
                MovementType.purchase_in
                if payment.direction is PaymentDirection.received
                else MovementType.sale_out
            ),
            weight_g_delta=(
                weight if payment.direction is PaymentDirection.received else -weight
            ),
            reference_type="payment",
            reference_id=payment.id,
            notes=f"{payment.payment_no}: {weight}g of {payment.gold_purity}k taken in exchange",
            user_id=current.id,
        )

    if invoice is not None:
        await sales.refresh_status(db, invoice)

    await log_action(
        db,
        user=current,
        action="payment.create",
        resource_type="payment",
        resource_id=payment.id,
        details={
            "payment_no": payment.payment_no,
            "method": payment.method.value,
            "direction": payment.direction.value,
            "amount": str(amount),
            "invoice_no": invoice.invoice_no if invoice else None,
            "entry_no": entry.entry_no,
        },
    )
    await db.commit()
    return (await decorate_payments(db, [await _load(db, payment.id)]))[0]


@router.post(
    "/{payment_id}/reverse",
    response_model=PaymentRead,
    dependencies=[reverse, confirm],
)
async def reverse_payment(
    payment_id: int,
    db: DbSession,
    current: CurrentUser,
    payload: PaymentReverseRequest | None = None,
) -> PaymentRead:
    """
    Cancel a payment by posting the mirror of its entry.

    The row is kept and re-read as reversed, because a customer disputing a
    receipt needs to see both that the money was taken and that it was handed
    back. Every balance derived from payments filters reversed ones out, so the
    invoice this was settling goes back to outstanding by itself.
    """
    payment = await _load(db, payment_id)
    reversal = await sales.reverse_payment(db, payment, user_id=current.id)

    # Metal handed back has to leave the melt pot too. The ledger reversal above
    # takes it off 1130; without this the stock ledger keeps counting grams the
    # shop returned across the counter.
    if payment.method is PaymentMethod.gold_exchange and payment.gold_purity is not None:
        pot = await purchasing.raw_gold_item(db, purity=int(payment.gold_purity))
        weight = Decimal(str(payment.gold_weight_g or 0))
        if weight:
            await post_movement(
                db,
                item=pot,
                type=(
                    MovementType.sale_out
                    if payment.direction is PaymentDirection.received
                    else MovementType.purchase_in
                ),
                weight_g_delta=(
                    -weight if payment.direction is PaymentDirection.received else weight
                ),
                reference_type="payment",
                reference_id=payment.id,
                notes=f"{payment.payment_no} reversed — metal returned",
                user_id=current.id,
            )

    if payment.invoice_id is not None:
        invoice = await db.get(Invoice, payment.invoice_id)
        if invoice is not None:
            await sales.refresh_status(db, invoice)

    await log_action(
        db,
        user=current,
        action="payment.reverse",
        resource_type="payment",
        resource_id=payment.id,
        details={
            "payment_no": payment.payment_no,
            "amount": str(d(payment.amount)),
            "reversal_no": reversal.entry_no,
            "reason": payload.reason if payload else None,
        },
    )
    await db.commit()
    return (await decorate_payments(db, [await _load(db, payment.id)]))[0]
