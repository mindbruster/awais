from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.api.v1.payments import decorate_payments
from app.models.customer import Customer
from app.models.gold_rate import GoldRate
from app.models.inventory import InventoryItem
from app.models.invoice import GoldCharge, Invoice, InvoiceItem, InvoiceStatus, SaleType
from app.models.payment import Payment, PaymentDirection, PaymentMethod
from app.models.product import Product, ProductStatus
from app.models.stock_movement import MovementType
from app.schemas.invoice import InvoiceCreate, InvoiceDetail, InvoiceRead
from app.services import branches, sales
from app.services.audit import log_action
from app.services.inventory import post_movement
from app.services.ledger import customer_balance
from app.services.pricing import DEFAULT_RATTI_BASE, invoice_totals, price_line
from app.services.gold_rate import rate_in_force
from app.services.serial import next_invoice_no
from app.services.whatsapp import render_invoice_message, send_text


async def _current_gold_rate(db, currency, purity: int = 24) -> Decimal:
    """Most recent rate for (currency, purity) — Decimal('0') if none set."""
    rate = await rate_in_force(db, currency=currency, purity=purity)
    return Decimal(str(rate.rate_per_g)) if rate else Decimal("0")

router = APIRouter()
read = Depends(require_perm("invoice:read"))
write = Depends(require_perm("invoice:write"))
issue_perm = Depends(require_perm("invoice:issue"))
mark_paid_perm = Depends(require_perm("invoice:mark_paid"))
void_perm = Depends(require_perm("invoice:void"))


async def _load_invoice(db, invoice_id: int, *, lock: bool = False) -> Invoice:
    """
    Always re-fetch the full row after a mutating commit. Refreshing only
    `attribute_names=["items"]` leaves columns with `onupdate=now()` (e.g.
    `updated_at`) expired, which then triggers a sync lazy-load during
    Pydantic serialization (MissingGreenlet error).

    `lock=True` on the three paths that change an invoice's status. Each of
    them reads the status, decides, and then writes — issuing deducts stock and
    posts a receivable, marking paid mints a payment, voiding reverses both. Two
    requests arriving together both pass the status check and both act, which
    means stock deducted twice or the same bill posted to the books twice, and
    unpicking that needs hand-written reversals. The lock is on the bare id
    because the row eager-joins its customer and Postgres refuses FOR UPDATE
    across an outer join.
    """
    if lock:
        await db.execute(select(Invoice.id).where(Invoice.id == invoice_id).with_for_update())
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id)
        .execution_options(populate_existing=True)
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return result


async def _detail(db, invoice: Invoice) -> InvoiceDetail:
    """
    One invoice with its settlement attached.

    `amount_paid` and `balance_due` are summed from the payment rows on every
    read rather than stored on the invoice: a cached figure would need
    maintaining by every path that takes, reverses or voids money, and the
    first one that forgets leaves a balance nobody can reconcile.
    """
    paid, due = await sales.settlement(db, invoice)
    payments = list(
        (
            await db.execute(
                select(Payment)
                .where(Payment.invoice_id == invoice.id)
                .order_by(Payment.paid_at, Payment.id)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    return InvoiceDetail(
        **InvoiceRead.model_validate(invoice).model_dump(),
        amount_paid=paid,
        balance_due=due,
        customer_balance=await customer_balance(db, invoice.customer_id),
        payments=await decorate_payments(db, payments),
    )


def _recompute(invoice: Invoice) -> None:
    line_totals: list[Decimal] = []
    # On a trade bill this accumulates the metal the buyer must hand over. On a
    # counter bill the same grams are already paid for in the money total, and
    # the figure stays zero so nothing can bill for the gold twice.
    charged_in = (invoice.gold_charged_in or GoldCharge.rupees).value
    fine_total = Decimal("0")
    for it in invoice.items:
        # Line rate falls back to invoice rate when not set ( > 0 ). Persisted
        # column default is 0 so callers omitting the field still get the
        # invoice-level fallback they expect.
        rate = (
            it.gold_rate_per_g
            if it.gold_rate_per_g is not None and Decimal(str(it.gold_rate_per_g)) > 0
            else invoice.gold_rate_per_g
        )
        gold_amount, stone_amount, line_total, fine_g = price_line(
            gold_weight_g=Decimal(str(it.gold_weight_g)),
            gold_purity=it.gold_purity,
            # The assayed fineness when the line carries one, so the money and
            # the metal are worked out from the same number.
            gold_tunch_pct=(
                Decimal(str(it.gold_tunch_pct)) if it.gold_tunch_pct is not None else None
            ),
            gold_charged_in=charged_in,
            gold_rate_per_g=Decimal(str(rate)),
            stone_weight_ct=Decimal(str(it.stone_weight_ct)),
            stone_rate_per_ct=Decimal(str(it.stone_rate_per_ct)),
            labor_amount=Decimal(str(it.labor_amount)),
            line_discount=Decimal(str(it.line_discount or 0)),
            discount_ratti=Decimal(str(it.discount_ratti or 0)),
            # Rows predating the column carry NULL/0; fall back to the customary
            # base rather than dividing by zero.
            ratti_base=int(it.ratti_base or DEFAULT_RATTI_BASE),
            # Wastage marks the metal up before the ratti discount gives some of
            # it back. Both levers are on the line and both have to reach
            # pricing, or the customer is billed on the net weight and the
            # shop's main margin lever silently does nothing.
            sale_wastage_pct=Decimal(str(it.sale_wastage_pct or 0)),
            sale_wastage_g=Decimal(str(it.sale_wastage_g or 0)),
            # Stock deduction and the profit report both scale by quantity, so
            # pricing must too — otherwise a multi-unit line ships and costs N
            # pieces while billing for one.
            quantity=it.quantity or 1,
        )
        it.gold_amount = gold_amount
        it.stone_amount = stone_amount
        it.line_total = line_total
        line_totals.append(line_total)
        fine_total += fine_g

    subtotal, total = invoice_totals(
        line_totals=line_totals,
        gold_rate_per_g=Decimal(str(invoice.gold_rate_per_g)),
        discount_amount=Decimal(str(invoice.discount_amount)),
        discount_weight_g=Decimal(str(invoice.discount_weight_g)),
        tax_amount=Decimal(str(invoice.tax_amount)),
        gold_charged_in=charged_in,
    )
    # The round-off is applied here rather than inside invoice_totals because it
    # is not a pricing rule: it is the paisa the counter waives to reach a
    # figure the customer can hand over. Stored as its own column so the margin
    # report can see it instead of it vanishing into the discount. Positive
    # rounds the total down, negative rounds it up.
    round_off = Decimal(str(invoice.round_off or 0))
    total = max(total - round_off, Decimal("0")).quantize(Decimal("0.01"))
    invoice.subtotal = subtotal
    invoice.total = total

    if charged_in == GoldCharge.grams.value:
        # A bill-level discount quoted in grams comes off the metal here rather
        # than off the money, because on this kind of bill the metal is what was
        # being discounted. Floored at nothing: a discount larger than the piece
        # would otherwise have the shop handing metal back.
        fine_total = max(
            fine_total - Decimal(str(invoice.discount_weight_g or 0)), Decimal("0")
        )
        invoice.metal_due_fine_g = fine_total.quantize(Decimal("0.0001"))
    else:
        invoice.metal_due_fine_g = Decimal("0.0000")


@router.get("", response_model=list[InvoiceRead], dependencies=[read])
async def list_invoices(
    db: DbSession,
    q: str | None = Query(default=None, description="Search invoice_no"),
    status_eq: InvoiceStatus | None = Query(default=None, alias="status"),
    sale_type: SaleType | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Invoice]:
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .order_by(Invoice.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_eq:
        stmt = stmt.where(Invoice.status == status_eq)
    if sale_type:
        stmt = stmt.where(Invoice.sale_type == sale_type)
    if customer_id is not None:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if q:
        stmt = stmt.where(Invoice.invoice_no.ilike(f"%{q}%"))
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "",
    response_model=InvoiceDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_invoice(
    payload: InvoiceCreate, db: DbSession, current: CurrentUser
) -> InvoiceDetail:
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid customer_id")

    # Auto-fill gold rate from /gold-rates/current when caller didn't supply one.
    # Keeps invoice pricing aligned with the daily-rate master without forcing
    # the UI to fetch /current itself.
    invoice_rate = Decimal(str(payload.gold_rate_per_g))
    if invoice_rate == 0:
        invoice_rate = await _current_gold_rate(db, payload.currency)

    # Which counter took the sale. Every money report is sliced by this the
    # moment a second shop opens.
    till = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)

    invoice = Invoice(
        invoice_no=await next_invoice_no(db),
        branch_id=till.id,
        sale_type=payload.sale_type,
        seller_id=payload.seller_id,
        kind=payload.kind,
        status=InvoiceStatus.draft,
        customer_id=payload.customer_id,
        currency=payload.currency,
        gold_rate_per_g=invoice_rate,
        # Taken from the customer, not asked for. A jeweller always settles the
        # metal in metal and a counter customer always pays rupees, so the shop
        # has one right answer per buyer and no reason to be offered a choice
        # it could get wrong. Snapshotted onto the bill so reclassifying the
        # customer later cannot rewrite what this document already means.
        gold_charged_in=GoldCharge.grams if customer.is_trade else GoldCharge.rupees,
        discount_amount=payload.discount_amount,
        discount_weight_g=payload.discount_weight_g,
        tax_amount=payload.tax_amount,
        bill_book_no=payload.bill_book_no,
        term_days=payload.term_days,
        round_off=payload.round_off,
        notes=payload.notes,
    )
    invoice.items = [InvoiceItem(**it.model_dump()) for it in payload.items]
    _recompute(invoice)
    db.add(invoice)
    await db.commit()
    return await _detail(db, await _load_invoice(db, invoice.id))


@router.get("/{invoice_id}", response_model=InvoiceDetail, dependencies=[read])
async def get_invoice(invoice_id: int, db: DbSession) -> InvoiceDetail:
    return await _detail(db, await _load_invoice(db, invoice_id))


@router.post(
    "/{invoice_id}/issue",
    response_model=InvoiceDetail,
    dependencies=[issue_perm, Depends(require_password_confirm)],
)
async def issue_invoice(
    invoice_id: int, db: DbSession, current: CurrentUser
) -> InvoiceDetail:
    """
    Issue a draft invoice: deduct stock for each linked product on a normal
    sale, and post the sale to the books.

    Stock and the ledger move together or not at all. An invoice that shipped
    metal without recording a receivable is exactly the disagreement between
    the two that this system exists to prevent, so both happen in the one
    transaction.
    """
    invoice = await _load_invoice(db, invoice_id, lock=True)
    if invoice.status != InvoiceStatus.draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft invoices can be issued")

    is_normal = invoice.sale_type == SaleType.normal

    for item in invoice.items:
        if item.product_id is None:
            continue
        product = await db.get(Product, item.product_id)
        if product is None:
            continue

        if is_normal:
            # Plan: normal sales deduct stock immediately.
            inv_stmt = select(InventoryItem).where(InventoryItem.product_id == product.id)
            inventory = (await db.execute(inv_stmt)).scalars().first()
            if inventory is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Product '{product.serial_no}' has no inventory record.",
                )
            # Deduct the weights recorded on the *product*, not the ones typed
            # onto the invoice line. The inventory row was created from the
            # product's figures at job completion; billing a slightly different
            # weight (which is routine — wastage, rounding, negotiation) would
            # otherwise drift the snapshot, or overshoot the negative-stock
            # guard and abort the issue half-way through.
            await post_movement(
                db,
                item=inventory,
                type=MovementType.sale_out,
                quantity_delta=-item.quantity,
                weight_g_delta=-Decimal(str(product.gold_weight_g or 0)) * item.quantity,
                weight_ct_delta=-Decimal(str(product.stone_weight_ct or 0)) * item.quantity,
                reference_type="invoice",
                reference_id=invoice.id,
                notes=f"Invoice {invoice.invoice_no} (normal sale)",
                user_id=current.id,
            )
            product.status = ProductStatus.sold
        else:
            # Plan: on-approval does NOT deduct stock. Track via product.status only.
            product.status = ProductStatus.on_approval

    invoice.status = InvoiceStatus.issued
    invoice.issued_at = datetime.now(timezone.utc)
    # The customer now owes the shop: debit Customers, credit Sales.
    entry = await sales.post_invoice_issued(db, invoice, user_id=current.id)
    await log_action(
        db, user=current,
        action="invoice.issue",
        resource_type="invoice", resource_id=invoice.id,
        details={
            "invoice_no": invoice.invoice_no,
            "sale_type": invoice.sale_type.value,
            "currency": invoice.currency.value,
            "total": str(invoice.total),
            "entry_no": entry.entry_no if entry else None,
        },
    )
    await db.commit()
    return await _detail(db, await _load_invoice(db, invoice.id))


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceDetail, dependencies=[mark_paid_perm])
async def mark_paid(invoice_id: int, db: DbSession, current: CurrentUser) -> InvoiceDetail:
    """
    Settle the whole outstanding balance in cash, in one click.

    This used to flip a status flag, which is why nobody could say how much had
    been taken, when, or by what method. It is now a **shortcut that records a
    real cash payment** for whatever is still owed: it mints a payment row,
    posts it to the ledger (debit Cash in Hand, credit Customers) and lets the
    status follow the money like every other settlement. `paid` is therefore a
    summary of the payment rows, never a claim made independently of them.

    Anything other than "the customer handed over the full balance in notes" —
    part payment, a bank transfer, old gold — goes through POST /payments,
    which is the same code path with the details filled in.
    """
    invoice = await _load_invoice(db, invoice_id, lock=True)
    if invoice.status is not InvoiceStatus.issued:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only issued invoices can be marked paid")

    _, due = await sales.settlement(db, invoice)
    if due <= 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{invoice.invoice_no} has nothing outstanding — there is no payment to record.",
        )

    payment = Payment(
        payment_no=await sales.next_payment_no(db),
        invoice_id=invoice.id,
        customer_id=invoice.customer_id,
        method=PaymentMethod.cash,
        direction=PaymentDirection.received,
        amount=due,
        paid_at=datetime.now(timezone.utc),
        reference=f"Marked paid — {invoice.invoice_no}",
        created_by_user_id=current.id,
    )
    db.add(payment)
    # The entry carries the payment's id as its source, so the row has to exist
    # before it can be posted against.
    await db.flush()

    customer = await db.get(Customer, invoice.customer_id)
    entry = await sales.post_payment(
        db, payment, customer=customer, invoice=invoice, user_id=current.id
    )
    payment.journal_entry_id = entry.id
    await sales.refresh_status(db, invoice)

    await log_action(
        db, user=current,
        action="invoice.mark_paid",
        resource_type="invoice", resource_id=invoice.id,
        details={
            "invoice_no": invoice.invoice_no,
            "total": str(invoice.total),
            "payment_no": payment.payment_no,
            "amount": str(due),
            "entry_no": entry.entry_no,
        },
    )
    await db.commit()
    return await _detail(db, await _load_invoice(db, invoice.id))


@router.post("/{invoice_id}/send-whatsapp", dependencies=[read])
async def send_whatsapp(invoice_id: int, db: DbSession) -> dict:
    """Send an invoice summary to the customer's phone via WhatsApp."""
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id)
    )
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    if not invoice.customer.phone:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Customer has no phone number on file.",
        )
    body = render_invoice_message(invoice, invoice.customer)
    result = await send_text(invoice.customer.phone, body)
    return {
        "provider": result.provider,
        "message_sid": result.message_sid,
        "to": invoice.customer.phone,
    }


@router.post(
    "/{invoice_id}/void",
    response_model=InvoiceDetail,
    dependencies=[void_perm, Depends(require_password_confirm)],
)
async def void_invoice(
    invoice_id: int, db: DbSession, current: CurrentUser
) -> InvoiceDetail:
    """
    Void an issued invoice: put the stock back and reverse what it posted.

    A voided invoice is corrected, never erased — the original entry stays in
    the journal with a reversal pointing at it, so the books can still explain
    how the receivable appeared and why it went away.
    """
    invoice = await _load_invoice(db, invoice_id, lock=True)
    if invoice.status not in (InvoiceStatus.draft, InvoiceStatus.issued):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot void in current status")

    # Money already taken against this bill has to be dealt with first. Voiding
    # underneath a live payment would leave cash in the till credited to an
    # invoice that no longer exists, and the customer's balance would go into
    # credit without anyone deciding that.
    taken = await sales.live_payment_count(db, invoice.id)
    if taken:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{invoice.invoice_no} has {taken} payment(s) recorded against it. Reverse or "
            "refund them before voiding the bill.",
        )

    if invoice.status == InvoiceStatus.issued:
        is_normal = invoice.sale_type == SaleType.normal
        for item in invoice.items:
            if item.product_id is None:
                continue
            product = await db.get(Product, item.product_id)
            if product is None:
                continue

            if is_normal:
                # Reverse the sale_out movement that issue_invoice posted.
                inv_stmt = select(InventoryItem).where(InventoryItem.product_id == product.id)
                inventory = (await db.execute(inv_stmt)).scalars().first()
                if inventory is None:
                    continue
                # Mirror of the deduction in issue_invoice — must use the same
                # source of truth (the product) or a void won't restore stock
                # to where it was.
                await post_movement(
                    db,
                    item=inventory,
                    type=MovementType.sale_return_in,
                    quantity_delta=item.quantity,
                    weight_g_delta=Decimal(str(product.gold_weight_g or 0)) * item.quantity,
                    weight_ct_delta=Decimal(str(product.stone_weight_ct or 0)) * item.quantity,
                    reference_type="invoice",
                    reference_id=invoice.id,
                    notes=f"Voided invoice {invoice.invoice_no}",
                    user_id=current.id,
                )
            # On-approval: stock was never moved; just clear the marker.
            product.status = ProductStatus.in_stock

    reversals = await sales.reverse_invoice_entries(db, invoice, user_id=current.id)
    invoice.status = InvoiceStatus.void
    await log_action(
        db, user=current,
        action="invoice.void",
        resource_type="invoice", resource_id=invoice.id,
        details={
            "invoice_no": invoice.invoice_no,
            "sale_type": invoice.sale_type.value,
            "previous_status": "issued" if invoice.issued_at else "draft",
            "reversals": [e.entry_no for e in reversals],
        },
    )
    await db.commit()
    return await _detail(db, await _load_invoice(db, invoice.id))
