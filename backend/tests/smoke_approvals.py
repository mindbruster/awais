"""
Non-destructive smoke test for goods on approval.

The invariant under test is the one that matters: a piece is in exactly one
place — on the shelf, out on a memo, or sold, never two. Everything runs inside
a transaction that is rolled back.
"""
import asyncio
import logging
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

logging.disable(logging.INFO)

from app.core.database import SessionLocal  # noqa: E402
from app.models.approval import Approval, ApprovalLineStatus, ApprovalStatus  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.product import Product, ProductStatus  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import approvals as svc  # noqa: E402
from app.services import branches as branch_svc  # noqa: E402

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
        if customer is None:
            print("Need a customer on file; skipping.")
            raise SystemExit(0)
        branch = await branch_svc.default_branch(db)

        def make(serial: str) -> Product:
            p = Product(
                serial_no=serial,
                branch_id=branch.id,
                name=f"Smoke piece {serial}",
                gold_weight_g=Decimal("10"),
                status=ProductStatus.in_stock,
            )
            db.add(p)
            return p

        a_piece, b_piece, c_piece = make("ZZ-A"), make("ZZ-B"), make("ZZ-C")
        await db.flush()

        approval = Approval(
            approval_no=await svc.next_approval_no(db),
            customer_id=customer.id,
            branch_id=branch.id,
            status=ApprovalStatus.out,
            due_date=date.today() - timedelta(days=3),
        )
        db.add(approval)
        await db.flush()
        approval.customer = customer
        approval.branch = branch
        print(f"       approval_no = {approval.approval_no}")
        check("memo number minted", approval.approval_no.startswith("APR-"))

        # --- issue --------------------------------------------------------------
        await svc.issue(
            db, approval, [a_piece.id, b_piece.id, c_piece.id], user_id=admin.id if admin else None
        )
        await db.refresh(a_piece)
        await db.refresh(approval)
        check("issuing takes the piece off the shelf",
              a_piece.status is ProductStatus.on_approval, f"got {a_piece.status}")
        check("the memo is out", approval.status is ApprovalStatus.out)
        issued_lines = await svc.lines_of(db, approval)
        check("all three lines are out",
              sum(1 for i in issued_lines if i.status is ApprovalLineStatus.out) == 3,
              f"got {[i.status for i in issued_lines]}")

        # --- a piece cannot go out twice ----------------------------------------
        second = Approval(
            approval_no=await svc.next_approval_no(db),
            customer_id=customer.id,
            branch_id=branch.id,
            status=ApprovalStatus.out,
        )
        db.add(second)
        await db.flush()
        second.customer = customer
        second.branch = branch
        try:
            await svc.issue(db, second, [a_piece.id], user_id=None)
            check("a piece already out cannot go out again", False, "no error raised")
        except HTTPException:
            check("a piece already out cannot go out again", True)

        try:
            await svc.issue(db, second, [b_piece.id, b_piece.id], user_id=None)
            check("the same piece twice on one memo is refused", False, "no error raised")
        except HTTPException:
            check("the same piece twice on one memo is refused", True)

        # --- partial return -----------------------------------------------------
        lines = {i.product_id: i.id for i in await svc.lines_of(db, approval)}
        moved = await svc.return_lines(db, approval, [lines[a_piece.id]], user_id=None)
        await db.refresh(a_piece)
        check("returning one piece moves one", moved == 1, f"got {moved}")
        check("a returned piece is back in stock",
              a_piece.status is ProductStatus.in_stock, f"got {a_piece.status}")
        check("the memo is now partly returned",
              approval.status is ApprovalStatus.partly_returned, f"got {approval.status}")

        # --- keeping a piece ----------------------------------------------------
        kept = await svc.mark_sold(db, approval, [lines[b_piece.id]], invoice_id=None, user_id=None)
        await db.refresh(b_piece)
        check("keeping a piece marks one line sold", kept == 1)
        check("a kept piece does NOT go back to stock",
              b_piece.status is ProductStatus.on_approval, f"got {b_piece.status}")
        check("the memo is still open with one piece out",
              approval.status is ApprovalStatus.partly_returned)

        # --- returning an already-settled line is a no-op, not an error ---------
        again = await svc.return_lines(db, approval, [lines[a_piece.id]], user_id=None)
        check("returning an already-returned line moves nothing", again == 0, f"got {again}")

        # --- closing ------------------------------------------------------------
        await svc.return_lines(db, approval, [lines[c_piece.id]], user_id=None)
        check("the memo closes when nothing is left out",
              approval.status is ApprovalStatus.closed, f"got {approval.status}")
        check("closing stamps a time", approval.closed_at is not None)

        # --- cancel puts everything still out back ------------------------------
        third = Approval(
            approval_no=await svc.next_approval_no(db),
            customer_id=customer.id,
            branch_id=branch.id,
            status=ApprovalStatus.out,
        )
        db.add(third)
        await db.flush()
        third.customer = customer
        third.branch = branch
        await svc.issue(db, third, [a_piece.id], user_id=None)
        await db.refresh(a_piece)
        check("re-issuing a returned piece works", a_piece.status is ProductStatus.on_approval)

        await svc.cancel(db, third, reason="smoke", user_id=None)
        await db.refresh(a_piece)
        check("cancelling puts the piece back on the shelf",
              a_piece.status is ProductStatus.in_stock, f"got {a_piece.status}")
        check("a cancelled memo says so", third.status is ApprovalStatus.cancelled)
        check("the reason is kept", third.cancelled_reason == "smoke")

        await db.rollback()
        print("\n       rolled back — no changes committed")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
