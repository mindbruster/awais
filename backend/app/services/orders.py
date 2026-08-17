"""
The rules an order runs on.

Three things live here rather than in the router: the number a job is known by,
which state may follow which, and the bridge onto the workshop engine. All
three have to give the same answer whoever asks, and the third in particular is
where the value of this module is — an order does not reimplement costing,
wastage or department routing, it mints a `Design` and lets the machinery that
already exists do the work.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lock_keys
from app.models.design import Design, DesignStatus
from app.models.item import Item
from app.models.order import (
    ALLOWED_TRANSITIONS,
    CustomerOrder,
    OrderEvent,
    OrderKind,
    OrderStatus,
)
from app.services.routing import next_design_no


async def next_order_no(db: AsyncSession) -> str:
    """
    `ORD-YY-NNNNN`, counted off the highest suffix in use.

    Same discipline as every other document number in this system: derived from
    the maximum rather than a row count, so deleting one cannot hand the next
    caller a number the unique index will reject.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.ORDER_NO)
    )
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(CustomerOrder.order_no, r"(\d+)$"), Integer)), 0
                )
            ).where(CustomerOrder.order_no.like(f"ORD-{year}-%"))
        )
    ).scalar_one()
    return f"ORD-{year}-{int(highest) + 1:05d}"


def ensure_transition(order: CustomerOrder, to: OrderStatus) -> None:
    """
    Refuse a move the workflow does not allow.

    Stated as a table lookup rather than a chain of ifs so that the same rule
    can be handed to the client — a button the counter cannot use should not be
    offered, and both ends have to agree on which those are.
    """
    if to is order.status:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{order.order_no} is already {to.value.replace('_', ' ')}.",
        )
    allowed = ALLOWED_TRANSITIONS.get(order.status, set())
    if to not in allowed:
        nice = ", ".join(sorted(s.value.replace("_", " ") for s in allowed)) or "nothing"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{order.order_no} is {order.status.value.replace('_', ' ')} and can only move to "
            f"{nice}.",
        )


def record(
    db: AsyncSession,
    order: CustomerOrder,
    *,
    to: OrderStatus | None = None,
    note: str | None = None,
    user_id: int | None = None,
) -> OrderEvent:
    """Append to the order's own history — the version read out to a customer."""
    event = OrderEvent(
        order_id=order.id,
        from_status=order.status if to is not None else None,
        to_status=to,
        note=note,
        user_id=user_id,
    )
    db.add(event)
    return event


async def start_work(
    db: AsyncSession, order: CustomerOrder, *, item: Item, notes: str | None = None
) -> Design:
    """
    Put the job on the bench.

    This is the whole point of the module. Rather than growing a second,
    weaker copy of the workshop inside orders, the order mints a design and
    hands over: every leg, every gram of wastage, every rupee of labour is then
    tracked by machinery that is already tested and already posts to the ledger.

    Minting twice is refused. Two designs for one promise means two job cards
    on the floor for one piece, which is exactly how a shop loses track of it.
    """
    if order.design_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{order.order_no} is already on the bench as design #{order.design_id}.",
        )
    if order.status in (OrderStatus.delivered, OrderStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{order.order_no} is {order.status.value} — work cannot be started on it.",
        )

    design = Design(
        design_no=await next_design_no(db, item),
        item_id=item.id,
        # The piece is being made for this customer, not for stock. Carried onto
        # the design so the workshop floor can see whose job it is holding.
        customer_id=order.customer_id,
        status=DesignStatus.in_production,
        notes=notes or f"{order.order_no}: {order.title}",
    )
    db.add(design)
    await db.flush()

    order.design_id = design.id
    if order.status in (OrderStatus.draft, OrderStatus.confirmed):
        order.status = OrderStatus.in_progress
    return design


def intake_summary(order: CustomerOrder) -> str | None:
    """
    The customer's own metal, in one line.

    Only meaningful on a repair: on a commission the shop supplies everything,
    and printing "0 g taken in" on a job card would invite someone to reconcile
    against a number that was never a measurement.
    """
    if order.kind is not OrderKind.repair or order.intake_weight_g is None:
        return None
    # Quantised rather than interpolated raw. Straight off the attribute this
    # reads "4.2 g" before the row has been through the database and "4.2000 g"
    # afterwards — the same weight, printed two ways, on a line whose whole
    # purpose is to be the record that settles a dispute.
    grams = Decimal(str(order.intake_weight_g)).quantize(Decimal("0.001"))
    purity = f" {order.intake_purity}k" if order.intake_purity else ""
    return f"{grams} g{purity} taken in from the customer"
