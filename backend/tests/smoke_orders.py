"""
Non-destructive smoke test for customer orders and repairs.

Runs inside one transaction that is rolled back, so the developer's database is
left exactly as found. Exercises the service layer directly, which keeps it out
of the auth path.
"""
import asyncio
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.customer import Customer
from app.models.item import Item
from app.models.order import CustomerOrder, OrderKind, OrderStatus
from app.models.user import User
from app.services import branches as branch_svc
from app.services import orders as svc

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


async def main():
    async with SessionLocal() as db:
        admin = (await db.execute(select(User).limit(1))).scalars().first()
        customer = (await db.execute(select(Customer).limit(1))).scalars().first()
        item = (await db.execute(select(Item).limit(1))).scalars().first()
        if not (customer and item):
            print("Need at least one customer and one item on file; skipping.")
            raise SystemExit(0)

        branch = await branch_svc.default_branch(db)

        # --- a repair, taken in over the counter --------------------------------
        order = CustomerOrder(
            order_no=await svc.next_order_no(db),
            kind=OrderKind.repair,
            status=OrderStatus.draft,
            customer_id=customer.id,
            branch_id=branch.id,
            title="Smoke: resize ring",
            promised_date=date.today() - timedelta(days=2),
            estimate_amount=Decimal("2500"),
            intake_weight_g=Decimal("4.2"),
            intake_purity=22,
        )
        db.add(order)
        await db.flush()
        print(f"       order_no = {order.order_no}")
        check("order number minted", order.order_no.startswith("ORD-"))
        check(
            "intake summary reads as the shop would say it",
            svc.intake_summary(order) == "4.200 g 22k taken in from the customer",
            f"got {svc.intake_summary(order)!r}",
        )

        # --- the workflow refuses illegal moves ---------------------------------
        try:
            svc.ensure_transition(order, OrderStatus.delivered)
            check("draft cannot jump straight to delivered", False, "no error raised")
        except HTTPException:
            check("draft cannot jump straight to delivered", True)

        try:
            svc.ensure_transition(order, OrderStatus.draft)
            check("moving to the state it is already in is refused", False, "no error")
        except HTTPException:
            check("moving to the state it is already in is refused", True)

        svc.ensure_transition(order, OrderStatus.confirmed)
        check("draft → confirmed is allowed", True)
        order.status = OrderStatus.confirmed

        # --- putting it on the bench mints a design -----------------------------
        design = await svc.start_work(db, order, item=item)
        await db.flush()
        check("start_work mints a design", design.id is not None)
        check("design number follows the item", design.design_no.startswith(item.abbreviation.upper()))
        check("order now points at the design", order.design_id == design.id)
        check("the design is the customer's, not stock", design.customer_id == customer.id)
        check("order moved itself to in progress", order.status is OrderStatus.in_progress)

        try:
            await svc.start_work(db, order, item=item)
            check("a second design is refused", False, "no error raised")
        except HTTPException:
            check("a second design is refused", True)

        # --- ready, then back to the bench, then delivered ----------------------
        svc.ensure_transition(order, OrderStatus.ready)
        order.status = OrderStatus.ready
        svc.ensure_transition(order, OrderStatus.in_progress)
        check("a ready piece can go back to the bench", True)

        order.status = OrderStatus.ready
        svc.ensure_transition(order, OrderStatus.delivered)
        order.status = OrderStatus.delivered
        try:
            svc.ensure_transition(order, OrderStatus.in_progress)
            check("a delivered order is closed for good", False, "no error raised")
        except HTTPException:
            check("a delivered order is closed for good", True)

        # --- events ------------------------------------------------------------
        svc.record(db, order, note="smoke note", user_id=admin.id if admin else None)
        await db.flush()
        await db.refresh(order)
        check("events are recorded against the order", len(order.events) >= 1)

        await db.rollback()
        print("\n       rolled back — no changes committed")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
