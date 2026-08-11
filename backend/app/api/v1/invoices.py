from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.customer import Customer
from app.models.gold_rate import GoldRate
from app.models.inventory import InventoryItem
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus, SaleType
from app.models.product import Product, ProductStatus
from app.models.stock_movement import MovementType
from app.schemas.invoice import InvoiceCreate, InvoiceRead
from app.services.audit import log_action
from app.services.inventory import post_movement
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


async def _load_invoice(db, invoice_id: int) -> Invoice:
    """
    Always re-fetch the full row after a mutating commit. Refreshing only
    `attribute_names=["items"]` leaves columns with `onupdate=now()` (e.g.
    `updated_at`) expired, which then triggers a sync lazy-load during
    Pydantic serialization (MissingGreenlet error).
    """
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id)
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return result


def _recompute(invoice: Invoice) -> None:
    line_totals: list[Decimal] = []
    for it in invoice.items:
        # Line rate falls back to invoice rate when not set ( > 0 ). Persisted
        # column default is 0 so callers omitting the field still get the
        # invoice-level fallback they expect.
        rate = (
            it.gold_rate_per_g
            if it.gold_rate_per_g is not None and Decimal(str(it.gold_rate_per_g)) > 0
            else invoice.gold_rate_per_g
        )
        gold_amount, stone_amount, line_total = price_line(
            gold_weight_g=Decimal(str(it.gold_weight_g)),
            gold_purity=it.gold_purity,
            gold_rate_per_g=Decimal(str(rate)),
            stone_weight_ct=Decimal(str(it.stone_weight_ct)),
            stone_rate_per_ct=Decimal(str(it.stone_rate_per_ct)),
            labor_amount=Decimal(str(it.labor_amount)),
            line_discount=Decimal(str(it.line_discount or 0)),
            discount_ratti=Decimal(str(it.discount_ratti or 0)),
            # Rows predating the column carry NULL/0; fall back to the customary
            # base rather than dividing by zero.
            ratti_base=int(it.ratti_base or DEFAULT_RATTI_BASE),
            # Stock deduction and the profit report both scale by quantity, so
            # pricing must too — otherwise a multi-unit line ships and costs N
            # pieces while billing for one.
            quantity=it.quantity or 1,
        )
        it.gold_amount = gold_amount
        it.stone_amount = stone_amount
        it.line_total = line_total
        line_totals.append(line_total)

    subtotal, total = invoice_totals(
        line_totals=line_totals,
        gold_rate_per_g=Decimal(str(invoice.gold_rate_per_g)),
        discount_amount=Decimal(str(invoice.discount_amount)),
        discount_weight_g=Decimal(str(invoice.discount_weight_g)),
        tax_amount=Decimal(str(invoice.tax_amount)),
    )
    invoice.subtotal = subtotal
    invoice.total = total


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
    response_model=InvoiceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_invoice(payload: InvoiceCreate, db: DbSession) -> Invoice:
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid customer_id")

    # Auto-fill gold rate from /gold-rates/current when caller didn't supply one.
    # Keeps invoice pricing aligned with the daily-rate master without forcing
    # the UI to fetch /current itself.
    invoice_rate = Decimal(str(payload.gold_rate_per_g))
    if invoice_rate == 0:
        invoice_rate = await _current_gold_rate(db, payload.currency)

    invoice = Invoice(
        invoice_no=await next_invoice_no(db),
        sale_type=payload.sale_type,
        status=InvoiceStatus.draft,
        customer_id=payload.customer_id,
        currency=payload.currency,
        gold_rate_per_g=invoice_rate,
        discount_amount=payload.discount_amount,
        discount_weight_g=payload.discount_weight_g,
        tax_amount=payload.tax_amount,
        notes=payload.notes,
    )
    invoice.items = [InvoiceItem(**it.model_dump()) for it in payload.items]
    _recompute(invoice)
    db.add(invoice)
    await db.commit()
    return await _load_invoice(db, invoice.id)


@router.get("/{invoice_id}", response_model=InvoiceRead, dependencies=[read])
async def get_invoice(invoice_id: int, db: DbSession) -> Invoice:
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id)
    )
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


@router.post(
    "/{invoice_id}/issue",
    response_model=InvoiceRead,
    dependencies=[issue_perm, Depends(require_password_confirm)],
)
async def issue_invoice(
    invoice_id: int, db: DbSession, current: CurrentUser
) -> Invoice:
    """Issue a draft invoice. For normal sales, deduct stock for each linked product."""
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id)
    )
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
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
    await log_action(
        db, user=current,
        action="invoice.issue",
        resource_type="invoice", resource_id=invoice.id,
        details={
            "invoice_no": invoice.invoice_no,
            "sale_type": invoice.sale_type.value,
            "currency": invoice.currency.value,
            "total": str(invoice.total),
        },
    )
    await db.commit()
    return await _load_invoice(db, invoice.id)


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceRead, dependencies=[mark_paid_perm])
async def mark_paid(invoice_id: int, db: DbSession, current: CurrentUser) -> Invoice:
    stmt = (
        select(Invoice).options(selectinload(Invoice.items)).where(Invoice.id == invoice_id)
    )
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    if invoice.status not in (InvoiceStatus.issued,):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only issued invoices can be marked paid")
    invoice.status = InvoiceStatus.paid
    invoice.paid_at = datetime.now(timezone.utc)
    await log_action(
        db, user=current,
        action="invoice.mark_paid",
        resource_type="invoice", resource_id=invoice.id,
        details={"invoice_no": invoice.invoice_no, "total": str(invoice.total)},
    )
    await db.commit()
    return await _load_invoice(db, invoice.id)


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
    response_model=InvoiceRead,
    dependencies=[void_perm, Depends(require_password_confirm)],
)
async def void_invoice(
    invoice_id: int, db: DbSession, current: CurrentUser
) -> Invoice:
    """Void an issued invoice and reverse stock movements."""
    stmt = (
        select(Invoice).options(selectinload(Invoice.items)).where(Invoice.id == invoice_id)
    )
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    if invoice.status not in (InvoiceStatus.draft, InvoiceStatus.issued):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot void in current status")

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

    invoice.status = InvoiceStatus.void
    await log_action(
        db, user=current,
        action="invoice.void",
        resource_type="invoice", resource_id=invoice.id,
        details={
            "invoice_no": invoice.invoice_no,
            "sale_type": invoice.sale_type.value,
            "previous_status": "issued" if invoice.issued_at else "draft",
        },
    )
    await db.commit()
    return await _load_invoice(db, invoice.id)
