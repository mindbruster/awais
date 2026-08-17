"""
Work promised to a customer: commissions and repairs.

Nothing here posts to the ledger, and that is deliberate. An order is a promise
— it moves no metal and earns no money. The advance is an ordinary payment
against the customer, the delivery is an ordinary invoice, and the work itself
is an ordinary design with ordinary legs. This module links those three rather
than growing weaker copies of them, which is why it is small.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.core import clock
from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.customer import Customer
from app.models.design import Design
from app.models.item import Item
from app.models.order import (
    ALLOWED_TRANSITIONS,
    CustomerOrder,
    OrderEvent,
    OrderKind,
    OrderStatus,
)
from app.models.product import Product
from app.schemas.order import (
    OrderBoard,
    OrderCancel,
    OrderCreate,
    OrderDetail,
    OrderEventRead,
    OrderRead,
    OrderStartWork,
    OrderTransition,
    OrderUpdate,
)
from app.services import branches, orders as svc
from app.services.audit import log_action
from app.services.ledger import d

router = APIRouter()
read = Depends(require_perm("order:read"))
write = Depends(require_perm("order:write"))

# Jobs that are still the shop's problem. Used by the board counts and by the
# "open" filter, so both mean the same thing.
OPEN_STATUSES = (
    OrderStatus.draft,
    OrderStatus.confirmed,
    OrderStatus.in_progress,
    OrderStatus.ready,
)


def _overdue_days(order: CustomerOrder) -> int | None:
    """
    How late the job is, or None if it isn't.

    Only counted while the job is still open: a piece delivered three days
    after its promised date was late on the day, but it is not on the list of
    things anybody needs to chase this morning.
    """
    if order.promised_date is None or order.status not in OPEN_STATUSES:
        return None
    days = (clock.today() - order.promised_date).days
    return days if days > 0 else None


def _order_read(order: CustomerOrder, design_no: str | None) -> OrderRead:
    return OrderRead(
        id=order.id,
        created_at=order.created_at,
        updated_at=order.updated_at,
        order_no=order.order_no,
        kind=order.kind,
        status=order.status,
        customer_id=order.customer_id,
        customer_name=order.customer.name if order.customer else None,
        customer_phone=order.customer.phone if order.customer else None,
        branch_id=order.branch_id,
        branch_name=order.branch.name if order.branch else None,
        title=order.title,
        description=order.description,
        promised_date=order.promised_date,
        days_overdue=_overdue_days(order),
        estimate_amount=d(order.estimate_amount),
        intake_weight_g=(
            d(order.intake_weight_g) if order.intake_weight_g is not None else None
        ),
        intake_purity=order.intake_purity,
        intake_notes=order.intake_notes,
        image_url=order.image_url,
        product_id=order.product_id,
        design_id=order.design_id,
        design_no=design_no,
        invoice_id=order.invoice_id,
        delivered_at=order.delivered_at,
        cancelled_reason=order.cancelled_reason,
        notes=order.notes,
        allowed_transitions=sorted(
            ALLOWED_TRANSITIONS.get(order.status, set()), key=lambda s: s.value
        ),
    )


def _event_read(e: OrderEvent) -> OrderEventRead:
    return OrderEventRead(
        id=e.id,
        created_at=e.created_at,
        updated_at=e.updated_at,
        from_status=e.from_status,
        to_status=e.to_status,
        note=e.note,
        user_id=e.user_id,
    )


async def _design_no(db: DbSession, design_id: int | None) -> str | None:
    if design_id is None:
        return None
    design = await db.get(Design, design_id)
    return design.design_no if design else None


async def _detail(db: DbSession, order: CustomerOrder) -> OrderDetail:
    base = _order_read(order, await _design_no(db, order.design_id))
    return OrderDetail(**base.model_dump(), events=[_event_read(e) for e in order.events])


async def _get_order(db: DbSession, order_id: int) -> CustomerOrder:
    order = await db.get(CustomerOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.post("", response_model=OrderDetail, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def take_order(payload: OrderCreate, db: DbSession, current: CurrentUser) -> OrderDetail:
    """Take a job in over the counter."""
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    if payload.product_id is not None and await db.get(Product, payload.product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    branch = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)

    order = CustomerOrder(
        order_no=await svc.next_order_no(db),
        kind=payload.kind,
        status=OrderStatus.draft,
        customer_id=customer.id,
        branch_id=branch.id,
        title=payload.title.strip(),
        description=payload.description,
        promised_date=payload.promised_date,
        estimate_amount=payload.estimate_amount,
        intake_weight_g=payload.intake_weight_g,
        intake_purity=payload.intake_purity,
        intake_notes=payload.intake_notes,
        product_id=payload.product_id,
        notes=payload.notes,
    )
    db.add(order)
    await db.flush()

    svc.record(
        db, order,
        note=svc.intake_summary(order) or f"Taken in at {branch.name}",
        user_id=current.id,
    )
    await log_action(
        db, user=current,
        action="order.create",
        resource_type="customer_order", resource_id=order.id,
        details={
            "order_no": order.order_no,
            "kind": order.kind.value,
            "customer": customer.name,
            "promised": str(order.promised_date) if order.promised_date else None,
        },
    )
    await db.commit()
    await db.refresh(order)
    return await _detail(db, order)


@router.get("", response_model=list[OrderRead], dependencies=[read])
async def list_orders(
    db: DbSession,
    status_: OrderStatus | None = Query(default=None, alias="status"),
    kind: OrderKind | None = Query(default=None),
    branch_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    open_only: bool = Query(default=False, description="Anything not delivered or cancelled"),
    overdue: bool = Query(default=False, description="Past its promised date and still open"),
    q: str | None = Query(default=None, description="Order number or title"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[OrderRead]:
    stmt = select(CustomerOrder).order_by(CustomerOrder.id.desc()).limit(limit).offset(offset)
    if status_:
        stmt = stmt.where(CustomerOrder.status == status_)
    if kind:
        stmt = stmt.where(CustomerOrder.kind == kind)
    if branch_id is not None:
        stmt = stmt.where(CustomerOrder.branch_id == branch_id)
    if customer_id is not None:
        stmt = stmt.where(CustomerOrder.customer_id == customer_id)
    if open_only or overdue:
        stmt = stmt.where(CustomerOrder.status.in_(OPEN_STATUSES))
    if overdue:
        stmt = stmt.where(
            CustomerOrder.promised_date.is_not(None),
            CustomerOrder.promised_date < clock.today(),
        )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(CustomerOrder.order_no.ilike(like), CustomerOrder.title.ilike(like))
        )
    rows = list((await db.execute(stmt)).scalars().all())
    return [_order_read(r, await _design_no(db, r.design_id)) for r in rows]


@router.get("/board", response_model=OrderBoard, dependencies=[read])
async def board(db: DbSession, branch_id: int | None = Query(default=None)) -> OrderBoard:
    """
    The day's work, counted.

    Assembled server-side because the alternative is the client fetching every
    open order just to count them, and the counts are wanted on a screen that
    should load instantly.
    """

    def scoped(stmt):
        return stmt.where(CustomerOrder.branch_id == branch_id) if branch_id else stmt

    counts = dict(
        (
            await db.execute(
                scoped(
                    select(CustomerOrder.status, func.count(CustomerOrder.id)).group_by(
                        CustomerOrder.status
                    )
                )
            )
        ).all()
    )
    overdue = (
        await db.execute(
            scoped(
                select(func.count(CustomerOrder.id)).where(
                    CustomerOrder.status.in_(OPEN_STATUSES),
                    CustomerOrder.promised_date.is_not(None),
                    CustomerOrder.promised_date < clock.today(),
                )
            )
        )
    ).scalar_one()
    return OrderBoard(
        draft=int(counts.get(OrderStatus.draft, 0)),
        confirmed=int(counts.get(OrderStatus.confirmed, 0)),
        in_progress=int(counts.get(OrderStatus.in_progress, 0)),
        ready=int(counts.get(OrderStatus.ready, 0)),
        overdue=int(overdue),
    )


@router.get("/{order_id}", response_model=OrderDetail, dependencies=[read])
async def get_order(order_id: int, db: DbSession) -> OrderDetail:
    return await _detail(db, await _get_order(db, order_id))


@router.patch("/{order_id}", response_model=OrderDetail, dependencies=[write])
async def update_order(
    order_id: int, payload: OrderUpdate, db: DbSession, current: CurrentUser
) -> OrderDetail:
    order = await _get_order(db, order_id)
    if order.status in (OrderStatus.delivered, OrderStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{order.order_no} is {order.status.value} and can no longer be edited.",
        )
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(order, field, value)
    await log_action(
        db, user=current,
        action="order.update",
        resource_type="customer_order", resource_id=order.id,
        details={k: str(v) for k, v in data.items()},
    )
    await db.commit()
    await db.refresh(order)
    return await _detail(db, order)


@router.post("/{order_id}/status", response_model=OrderDetail, dependencies=[write])
async def move_order(
    order_id: int, payload: OrderTransition, db: DbSession, current: CurrentUser
) -> OrderDetail:
    """
    Move the job along.

    Cancellation is not available here — it reverses a promise and takes a
    reason, so it has its own endpoint.
    """
    order = await _get_order(db, order_id)
    if payload.to is OrderStatus.cancelled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cancelling an order needs a reason. Use the cancel endpoint.",
        )
    svc.ensure_transition(order, payload.to)
    svc.record(db, order, to=payload.to, note=payload.note, user_id=current.id)
    order.status = payload.to
    if payload.to is OrderStatus.delivered:
        order.delivered_at = datetime.now(timezone.utc)

    await log_action(
        db, user=current,
        action="order.status",
        resource_type="customer_order", resource_id=order.id,
        details={"order_no": order.order_no, "to": payload.to.value},
    )
    await db.commit()
    await db.refresh(order)
    return await _detail(db, order)


@router.post("/{order_id}/start-work", response_model=OrderDetail, dependencies=[write])
async def start_work(
    order_id: int, payload: OrderStartWork, db: DbSession, current: CurrentUser
) -> OrderDetail:
    """
    Mint the workshop job for this order.

    From here the piece is tracked by the routing engine like any other — the
    order simply holds the customer's side of it.
    """
    order = await _get_order(db, order_id)
    item = await db.get(Item, payload.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")

    design = await svc.start_work(db, order, item=item, notes=payload.notes)
    svc.record(
        db, order,
        note=f"On the bench as {design.design_no}",
        user_id=current.id,
    )
    await log_action(
        db, user=current,
        action="order.start_work",
        resource_type="customer_order", resource_id=order.id,
        details={"order_no": order.order_no, "design_no": design.design_no},
    )
    await db.commit()
    await db.refresh(order)
    return await _detail(db, order)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderDetail,
    # A cancelled order is a promise withdrawn from a named customer. It does
    # not reverse a ledger entry, but it is not something to do by misclick.
    dependencies=[write, Depends(require_password_confirm)],
)
async def cancel_order(
    order_id: int, payload: OrderCancel, db: DbSession, current: CurrentUser
) -> OrderDetail:
    order = await _get_order(db, order_id)
    svc.ensure_transition(order, OrderStatus.cancelled)
    # The design is deliberately left alone. Metal may already be out with a
    # karigar, and the workshop has its own cancel that puts it back — silently
    # abandoning the design here would strand that metal.
    svc.record(
        db, order, to=OrderStatus.cancelled, note=payload.reason, user_id=current.id
    )
    order.status = OrderStatus.cancelled
    order.cancelled_reason = payload.reason

    await log_action(
        db, user=current,
        action="order.cancel",
        resource_type="customer_order", resource_id=order.id,
        details={
            "order_no": order.order_no,
            "reason": payload.reason,
            "design_id": order.design_id,
        },
    )
    await db.commit()
    await db.refresh(order)
    return await _detail(db, order)
