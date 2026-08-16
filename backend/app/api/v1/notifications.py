"""
Messages to customers, and the record of them.

Nothing here sends on a schedule or on a status change. Every message is a
person at the counter deciding to send it, which is the only safe design: a
shop that auto-messages will eventually wish someone happy birthday on the day
of a bereavement, or announce a piece is ready that a colleague has just found
a fault in.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.core import clock
from app.api.deps import CurrentUser, DbSession, require_perm
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.notification import Notification, NotificationKind, NotificationStatus
from app.models.order import CustomerOrder
from app.schemas.notification import (
    NotificationPreview,
    NotificationRead,
    NotificationSend,
    OccasionRow,
    OccasionsReport,
)
from app.services import notifications as svc
from app.services.audit import log_action
from app.services.ledger import customer_balance, d

router = APIRouter()
read = Depends(require_perm("notification:read"))
send_perm = Depends(require_perm("notification:send"))


def _read(n: Notification) -> NotificationRead:
    return NotificationRead(
        id=n.id,
        created_at=n.created_at,
        updated_at=n.updated_at,
        kind=n.kind,
        channel=n.channel,
        status=n.status,
        customer_id=n.customer_id,
        customer_name=n.customer.name if n.customer else None,
        to_phone=n.to_phone,
        body=n.body,
        related_type=n.related_type,
        related_id=n.related_id,
        provider=n.provider,
        provider_message_id=n.provider_message_id,
        error=n.error,
        sent_at=n.sent_at,
    )


async def _context(
    db: DbSession, kind: NotificationKind, related_id: int | None
) -> tuple[Customer | None, dict, str | None, int | None]:
    """
    Gather what a template needs, and refuse a kind whose subject is missing.

    An order-ready message with no order behind it would render "your None is
    ready", which is worse than an error — it goes to a customer.
    """
    if kind in (
        NotificationKind.order_confirmed,
        NotificationKind.order_ready,
        NotificationKind.order_delivered,
    ):
        if related_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This message is about an order — send related_id."
            )
        order = await db.get(CustomerOrder, related_id)
        if order is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        return (
            order.customer,
            {
                "order_no": order.order_no,
                "title": order.title,
                "promised_date": (
                    order.promised_date.strftime("%d %b %Y") if order.promised_date else None
                ),
                "estimate_amount": order.estimate_amount,
            },
            "customer_order",
            order.id,
        )

    if kind is NotificationKind.invoice:
        if related_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This message is about an invoice — send related_id."
            )
        invoice = await db.get(Invoice, related_id)
        if invoice is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
        return (
            invoice.customer,
            {
                "invoice_no": invoice.invoice_no,
                "total": invoice.total,
                # Carried through so a dollar bill is quoted in dollars. The
                # invoice is the only document here that has a currency of its
                # own; balances and estimates are ledger figures, in rupees.
                "currency": invoice.currency,
            },
            "invoice",
            invoice.id,
        )

    return None, {}, None, None


@router.post("/preview", response_model=NotificationPreview, dependencies=[read])
async def preview(
    payload: NotificationSend, db: DbSession
) -> NotificationPreview:
    """
    What would go out, before it goes out.

    A message to a customer cannot be unsent, so the counter reads it first.
    """
    customer, ctx, rel_type, rel_id = await _context(db, payload.kind, payload.related_id)
    if customer is None and payload.customer_id is not None:
        customer = await db.get(Customer, payload.customer_id)
    if customer is None and payload.kind is not NotificationKind.custom:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No customer to send this to.")

    if payload.kind is NotificationKind.payment_reminder and customer is not None:
        ctx["balance"] = await customer_balance(db, customer.id)

    body = payload.body or svc.render(payload.kind, customer=customer, ctx=ctx)
    phone = (payload.to_phone or (customer.phone if customer else None) or "").strip()
    return NotificationPreview(
        body=body,
        customer_id=customer.id if customer else None,
        customer_name=customer.name if customer else None,
        to_phone=phone or None,
        related_type=rel_type,
        related_id=rel_id,
        sendable=bool(phone),
        note=(
            None
            if phone
            else "No phone number on file for this customer — the message can't be delivered."
        ),
    )


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED, dependencies=[send_perm])
async def send(
    payload: NotificationSend, db: DbSession, current: CurrentUser
) -> NotificationRead:
    """
    Send it, and record the attempt.

    Returns 201 even when nothing left the building: the row says what
    happened. Failing the request would tell the counter that their click did
    not register, which is not the same thing as the customer not being told.
    """
    customer, ctx, rel_type, rel_id = await _context(db, payload.kind, payload.related_id)
    if customer is None and payload.customer_id is not None:
        customer = await db.get(Customer, payload.customer_id)
    if customer is None and payload.kind is not NotificationKind.custom:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No customer to send this to.")

    if payload.kind is NotificationKind.payment_reminder and customer is not None:
        ctx["balance"] = await customer_balance(db, customer.id)

    body = payload.body or svc.render(payload.kind, customer=customer, ctx=ctx)
    note = await svc.dispatch(
        db,
        kind=payload.kind,
        customer=customer,
        body=body,
        related_type=rel_type,
        related_id=rel_id,
        user_id=current.id,
        to_phone=payload.to_phone,
    )
    await log_action(
        db, user=current,
        action="notification.send",
        resource_type="notification", resource_id=note.id,
        details={
            "kind": note.kind.value,
            "status": note.status.value,
            "customer": customer.name if customer else None,
        },
    )
    await db.commit()
    await db.refresh(note)
    return _read(note)


@router.get("", response_model=list[NotificationRead], dependencies=[read])
async def list_notifications(
    db: DbSession,
    kind: NotificationKind | None = Query(default=None),
    status_: NotificationStatus | None = Query(default=None, alias="status"),
    customer_id: int | None = Query(default=None),
    related_type: str | None = Query(default=None),
    related_id: int | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[NotificationRead]:
    stmt = select(Notification).order_by(Notification.id.desc()).limit(limit).offset(offset)
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    if status_:
        stmt = stmt.where(Notification.status == status_)
    if customer_id is not None:
        stmt = stmt.where(Notification.customer_id == customer_id)
    if related_type:
        stmt = stmt.where(Notification.related_type == related_type)
    if related_id is not None:
        stmt = stmt.where(Notification.related_id == related_id)
    return [_read(n) for n in (await db.execute(stmt)).scalars().all()]


@router.get("/occasions", response_model=OccasionsReport, dependencies=[read])
async def occasions(
    db: DbSession,
    days: int = Query(default=7, ge=0, le=60),
) -> OccasionsReport:
    """
    Birthdays and anniversaries coming up.

    These have been on the customer record since the beginning and nothing has
    ever read them. A jeweller's best repeat-sale prompt was sitting in the
    database unused.
    """
    today = clock.today()
    rows = (
        await db.execute(
            select(Customer).where(
                or_(
                    Customer.date_of_birth.is_not(None),
                    Customer.anniversary.is_not(None),
                )
            )
        )
    ).unique().scalars().all()

    out: list[OccasionRow] = []
    for c in rows:
        for day, kind in (
            (c.date_of_birth, NotificationKind.birthday),
            (c.anniversary, NotificationKind.anniversary),
        ):
            due = svc.occasion_within(day, today=today, window=days)
            if due is None:
                continue
            out.append(
                OccasionRow(
                    customer_id=c.id,
                    customer_name=c.name,
                    phone=c.phone,
                    kind=kind,
                    date=day,
                    days_away=due,
                    has_phone=bool((c.phone or "").strip()),
                )
            )
    out.sort(key=lambda r: (r.days_away, r.customer_name))
    return OccasionsReport(days=days, today=today, rows=out)
