"""
Non-destructive smoke test for the branch + transfer feature.

Everything happens inside one transaction that is rolled back at the end, so the
developer's database is left exactly as it was found. This is testing the
service layer directly rather than over HTTP, which keeps it out of the auth
path entirely.
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.branch import Branch, BranchTransfer, BranchTransferItem, TransferStatus
from app.models.inventory import InventoryItem, InventoryType
from app.models.user import User
from app.services import branches as svc

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

        default = await svc.default_branch(db)
        check("a default branch exists", default is not None, "")
        print(f"       default = {default.code} {default.name}")

        resolved = await svc.resolve_branch(db, requested_id=None, user=admin)
        check("resolve falls back to the default", resolved.id == default.id)

        # A second shop to move goods to.
        dest = Branch(code="ZZTEST", name="Smoke Test Branch", is_active=True, is_default=False)
        db.add(dest)
        await db.flush()
        check("second branch created", dest.id is not None)

        # A pot of raw gold at the source branch, with something in it.
        src = InventoryItem(
            type=InventoryType.raw_gold,
            label="Smoke 22k",
            branch_id=default.id,
            quantity=0,
            weight_g=Decimal("100"),
            weight_ct=Decimal("0"),
            purity=22,
        )
        db.add(src)
        await db.flush()

        transfer = BranchTransfer(
            transfer_no=await svc.next_transfer_no(db),
            from_branch=default,
            to_branch=dest,
            status=TransferStatus.draft,
        )
        db.add(transfer)
        await db.flush()
        print(f"       transfer_no = {transfer.transfer_no}")
        check("transfer number minted", transfer.transfer_no.startswith("TRF-"))

        db.add(
            BranchTransferItem(
                transfer_id=transfer.id,
                inventory_item_id=src.id,
                weight_g=Decimal("30"),
            )
        )
        await db.flush()
        await db.refresh(transfer)

        # --- send: stock leaves the source shelf -------------------------------
        await svc.send(db, transfer, user_id=admin.id if admin else None)
        await db.refresh(src)
        check("send sets status", transfer.status is TransferStatus.sent)
        check("send takes 30g off the source", Decimal(str(src.weight_g)) == Decimal("70"),
              f"got {src.weight_g}")

        mirror_before = (
            await db.execute(
                select(InventoryItem).where(
                    InventoryItem.branch_id == dest.id, InventoryItem.label == "Smoke 22k"
                )
            )
        ).scalars().first()
        check("goods are in transit, on neither shelf", mirror_before is None)

        # --- receive: it lands at the destination ------------------------------
        await svc.receive(db, transfer, user_id=admin.id if admin else None)
        await db.flush()
        mirror = (
            await db.execute(
                select(InventoryItem).where(
                    InventoryItem.branch_id == dest.id, InventoryItem.label == "Smoke 22k"
                )
            )
        ).scalars().first()
        check("receive sets status", transfer.status is TransferStatus.received)
        check("mirror pot created at destination", mirror is not None)
        if mirror:
            check("30g landed at the destination",
                  Decimal(str(mirror.weight_g)) == Decimal("30"), f"got {mirror.weight_g}")
        await db.refresh(src)
        check("source still at 70g after receive",
              Decimal(str(src.weight_g)) == Decimal("70"), f"got {src.weight_g}")

        # --- a second transfer, cancelled after sending ------------------------
        t2 = BranchTransfer(
            transfer_no=await svc.next_transfer_no(db),
            from_branch=default,
            to_branch=dest,
            status=TransferStatus.draft,
        )
        db.add(t2)
        await db.flush()
        db.add(
            BranchTransferItem(
                transfer_id=t2.id, inventory_item_id=src.id, weight_g=Decimal("20")
            )
        )
        await db.flush()
        await db.refresh(t2)
        await svc.send(db, t2, user_id=admin.id if admin else None)
        await db.refresh(src)
        check("second send takes it to 50g",
              Decimal(str(src.weight_g)) == Decimal("50"), f"got {src.weight_g}")

        await svc.cancel(db, t2, reason="smoke test", user_id=admin.id if admin else None)
        await db.refresh(src)
        check("cancel puts the 20g back",
              Decimal(str(src.weight_g)) == Decimal("70"), f"got {src.weight_g}")
        check("cancel sets status", t2.status is TransferStatus.cancelled)

        # --- refusals ----------------------------------------------------------
        from fastapi import HTTPException

        try:
            await svc.receive(db, t2, user_id=None)
            check("cancelled transfer refuses receive", False, "no error raised")
        except HTTPException:
            check("cancelled transfer refuses receive", True)

        try:
            await svc.send(db, transfer, user_id=None)
            check("received transfer refuses a second send", False, "no error raised")
        except HTTPException:
            check("received transfer refuses a second send", True)

        # --- letterhead --------------------------------------------------------
        # Documents head themselves with `print_name`, never with `name`. The
        # fallback matters: a shop that has not filled in its trading name still
        # gets a heading, rather than a bill that says nothing at the top.
        check(
            "a shop with no trading name still heads a bill",
            dest.print_name == "Smoke Test Branch",
            dest.print_name,
        )
        dest.letterhead_name = "SMOKE & SONS"
        check(
            "the trading name wins once it is set",
            dest.print_name == "SMOKE & SONS",
            dest.print_name,
        )

        # Leave the database exactly as found.
        await db.rollback()
        print("\n       rolled back — no changes committed")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
