"""
Branches, and moving stock between them.

Two rules live here rather than at the call sites. First, every row that has to
say where it is gets an answer even when the caller did not supply one — the
user's own branch, else the default — because a piece of stock filed at no
branch is invisible at every branch. Second, a transfer is a send and a
receive, and the metal in between belongs to neither shelf.

Nothing here posts to the ledger. Moving the shop's own goods between the
shop's own counters changes no balance; only the location changes. Posting an
entry for it would inflate turnover with movements that never earned a rupee.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lock_keys
from app.models.branch import (
    Branch,
    BranchTransfer,
    BranchTransferItem,
    TransferStatus,
)
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductStatus
from app.models.stock_movement import MovementType
from app.models.user import User
from app.services.inventory import post_movement
from app.services.ledger import d

SOURCE_TYPE = "branch_transfer"


async def default_branch(db: AsyncSession) -> Branch:
    """
    The branch everything falls back to.

    A unique partial index guarantees at most one, and the branches migration
    seeded one, so the only way to reach the error below is to have actively
    cleared the flag. That is a configuration fault and is worth saying out
    loud rather than silently filing stock under whichever branch sorts first.
    """
    row = (
        await db.execute(select(Branch).where(Branch.is_default.is_(True)).limit(1))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No default branch is set. Mark one branch as the default before recording "
            "stock or sales — every piece has to belong to a shop.",
        )
    return row


async def resolve_branch(
    db: AsyncSession, *, requested_id: int | None, user: User | None
) -> Branch:
    """
    Which branch a new row belongs to.

    Precedence is deliberate: what the caller said, then where the user works,
    then the default. A counter hand should never have to pick their own shop
    from a dropdown twenty times a day, and an owner posting for a specific
    branch must be able to override.
    """
    if requested_id is not None:
        branch = await db.get(Branch, requested_id)
        if branch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Branch #{requested_id} not found")
        if not branch.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{branch.name} is closed. Reopen it, or pick another branch.",
            )
        return branch
    if user is not None and user.branch_id is not None:
        branch = await db.get(Branch, user.branch_id)
        if branch is not None and branch.is_active:
            return branch
    return await default_branch(db)


async def next_transfer_no(db: AsyncSession) -> str:
    """`TRF-YY-NNNNN`, counted off the highest suffix in use.

    The same discipline as every other document number here: derived from the
    maximum rather than a row count, so deleting one does not hand the next
    caller a number the unique index will reject."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.BRANCH_TRANSFER_NO)
    )
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(BranchTransfer.transfer_no, r"(\d+)$"), Integer)),
                    0,
                )
            ).where(BranchTransfer.transfer_no.like(f"TRF-{year}-%"))
        )
    ).scalar_one()
    return f"TRF-{year}-{int(highest) + 1:05d}"


def ensure_sendable(transfer: BranchTransfer) -> None:
    if transfer.status is not TransferStatus.draft:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{transfer.transfer_no} is already {transfer.status.value} and cannot be sent again.",
        )
    if not transfer.items:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{transfer.transfer_no} has no lines. Add what is going before sending it.",
        )


def ensure_receivable(transfer: BranchTransfer) -> None:
    if transfer.status is not TransferStatus.sent:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{transfer.transfer_no} is {transfer.status.value}. Only a sent transfer can be "
            "received.",
        )


async def _mirror_item(
    db: AsyncSession, source: InventoryItem, branch: Branch
) -> InventoryItem:
    """
    The row at the receiving branch that matching stock lands in.

    Matched on branch, type, label and purity rather than created blindly:
    without this, every transfer of 22k bullion would open a new pot at the
    destination and the branch's stock report would show ten rows where the
    shelf holds one.
    """
    stmt = select(InventoryItem).where(
        InventoryItem.branch_id == branch.id,
        InventoryItem.type == source.type,
        InventoryItem.label == source.label,
        InventoryItem.product_id.is_(None),
    )
    stmt = (
        stmt.where(InventoryItem.purity == source.purity)
        if source.purity is not None
        else stmt.where(InventoryItem.purity.is_(None))
    )
    existing = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if existing is not None:
        return existing

    mirror = InventoryItem(
        type=source.type,
        label=source.label,
        location=source.location,
        branch_id=branch.id,
        quantity=0,
        weight_g=Decimal("0"),
        weight_ct=Decimal("0"),
        purity=source.purity,
    )
    db.add(mirror)
    await db.flush()
    return mirror


async def send(
    db: AsyncSession, transfer: BranchTransfer, *, user_id: int | None
) -> None:
    """
    Take the goods off the sending branch's shelf.

    Stock leaves here and does not arrive anywhere until the receive. That gap
    is the point: it is what lets the shop ask what is on the road.
    """
    ensure_sendable(transfer)

    for line in transfer.items:
        if line.product_id is not None:
            product = await db.get(Product, line.product_id)
            if product is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"Product #{line.product_id} not found"
                )
            if product.branch_id != transfer.from_branch_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{product.serial_no} is at {product.branch.name if product.branch else 'another branch'}, "
                    f"not {transfer.from_branch.name}. It cannot be sent from a shop that does not have it.",
                )
            if product.status is not ProductStatus.in_stock:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{product.serial_no} is {product.status.value.replace('_', ' ')} and cannot "
                    "be transferred.",
                )
            continue

        source = await db.get(InventoryItem, line.inventory_item_id)
        if source is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Inventory item #{line.inventory_item_id} not found"
            )
        if source.branch_id != transfer.from_branch_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{source.label} is not held at {transfer.from_branch.name}.",
            )
        await post_movement(
            db,
            item=source,
            type=MovementType.transfer_out,
            quantity_delta=-int(line.quantity or 0),
            weight_g_delta=-d(line.weight_g),
            weight_ct_delta=-d(line.weight_ct),
            reference_type=SOURCE_TYPE,
            reference_id=transfer.id,
            notes=f"{transfer.transfer_no} to {transfer.to_branch.name}",
            user_id=user_id,
        )

    transfer.status = TransferStatus.sent
    transfer.sent_at = datetime.now(timezone.utc)
    transfer.sent_by_id = user_id


async def receive(
    db: AsyncSession, transfer: BranchTransfer, *, user_id: int | None
) -> None:
    """Sign for the goods at the far end and put them on that branch's shelf."""
    ensure_receivable(transfer)

    for line in transfer.items:
        if line.product_id is not None:
            product = await db.get(Product, line.product_id)
            if product is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"Product #{line.product_id} not found"
                )
            # A finished piece moves whole: the branch it belongs to changes,
            # and so does the branch of the inventory row that carries it.
            product.branch_id = transfer.to_branch_id
            inv = (
                await db.execute(
                    select(InventoryItem).where(InventoryItem.product_id == product.id).limit(1)
                )
            ).scalar_one_or_none()
            if inv is not None:
                inv.branch_id = transfer.to_branch_id
                line.received_inventory_item_id = inv.id
            continue

        source = await db.get(InventoryItem, line.inventory_item_id)
        if source is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Inventory item #{line.inventory_item_id} not found"
            )
        mirror = await _mirror_item(db, source, transfer.to_branch)
        await post_movement(
            db,
            item=mirror,
            type=MovementType.transfer_in,
            quantity_delta=int(line.quantity or 0),
            weight_g_delta=d(line.weight_g),
            weight_ct_delta=d(line.weight_ct),
            reference_type=SOURCE_TYPE,
            reference_id=transfer.id,
            notes=f"{transfer.transfer_no} from {transfer.from_branch.name}",
            user_id=user_id,
        )
        line.received_inventory_item_id = mirror.id

    transfer.status = TransferStatus.received
    transfer.received_at = datetime.now(timezone.utc)
    transfer.received_by_id = user_id


async def cancel(
    db: AsyncSession, transfer: BranchTransfer, *, reason: str, user_id: int | None
) -> None:
    """
    Abandon a transfer.

    A draft has moved nothing and simply closes. A sent one has already taken
    stock off the sending shelf, so cancelling has to put it back there —
    otherwise the metal exists on no branch's books at all, which is the one
    outcome a transfer feature must never produce.
    """
    if transfer.status in (TransferStatus.received, TransferStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{transfer.transfer_no} is already {transfer.status.value}.",
        )

    if transfer.status is TransferStatus.sent:
        for line in transfer.items:
            if line.product_id is not None:
                continue
            source = await db.get(InventoryItem, line.inventory_item_id)
            if source is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"The stock line for item #{line.inventory_item_id} no longer exists, so the "
                    "goods cannot be put back. Restore it before cancelling.",
                )
            await post_movement(
                db,
                item=source,
                type=MovementType.transfer_in,
                quantity_delta=int(line.quantity or 0),
                weight_g_delta=d(line.weight_g),
                weight_ct_delta=d(line.weight_ct),
                reference_type=SOURCE_TYPE,
                reference_id=transfer.id,
                notes=f"{transfer.transfer_no} cancelled — returned to {transfer.from_branch.name}",
                user_id=user_id,
            )

    transfer.status = TransferStatus.cancelled
    transfer.notes = (transfer.notes + "\n" if transfer.notes else "") + f"Cancelled: {reason}"
