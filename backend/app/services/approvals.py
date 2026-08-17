"""
Goods on approval, and getting them back.

The invariant this module protects is simple and easy to break: a piece is in
exactly one place. On the shelf, out on a memo, or sold — never two of those.
The status on the product and the status on the memo line are two views of the
same fact, so they are only ever changed together, here.

Nothing posts to the ledger. A memo is not a sale.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lock_keys
from app.models.approval import (
    Approval,
    ApprovalItem,
    ApprovalLineStatus,
    ApprovalStatus,
)
from app.models.inventory import InventoryItem
from app.models.product import Product, ProductStatus
from app.models.stock_movement import MovementType
from app.services.inventory import post_movement

SOURCE_TYPE = "approval"


async def next_approval_no(db: AsyncSession) -> str:
    """`APR-YY-NNNNN`, counted off the highest suffix in use."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.APPROVAL_NO)
    )
    year = datetime.now(timezone.utc).strftime("%y")
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(Approval.approval_no, r"(\d+)$"), Integer)), 0
                )
            ).where(Approval.approval_no.like(f"APR-{year}-%"))
        )
    ).scalar_one()
    return f"APR-{year}-{int(highest) + 1:05d}"


async def lines_of(db: AsyncSession, approval: Approval) -> list[ApprovalItem]:
    """
    The memo's lines, fetched rather than read off the relationship.

    `approval.items` is only populated when the parent was loaded by a query
    that eager-loaded it. Rows added earlier in the same session leave it stale,
    and touching it then triggers a lazy load — which async SQLAlchemy refuses
    outright. Selecting is one cheap query and cannot be got wrong by a caller.
    """
    return list(
        (
            await db.execute(
                select(ApprovalItem)
                .where(ApprovalItem.approval_id == approval.id)
                .order_by(ApprovalItem.id)
            )
        ).scalars().all()
    )


async def _inventory_row(db: AsyncSession, product_id: int) -> InventoryItem | None:
    return (
        await db.execute(
            select(InventoryItem).where(InventoryItem.product_id == product_id).limit(1)
        )
    ).scalar_one_or_none()


async def _move(
    db: AsyncSession,
    product: Product,
    *,
    type: MovementType,
    delta: int,
    approval: Approval,
    note: str,
    user_id: int | None,
) -> None:
    """
    Mirror the piece's movement in the stock ledger.

    A finished piece carries quantity 1 on its inventory row. Skipped silently
    when there is no such row: some pieces predate the stock form, and refusing
    to let those out on approval would be punishing the shop for its own
    history rather than protecting anything.
    """
    row = await _inventory_row(db, product.id)
    if row is None:
        return
    await post_movement(
        db,
        item=row,
        type=type,
        quantity_delta=delta,
        reference_type=SOURCE_TYPE,
        reference_id=approval.id,
        notes=note,
        user_id=user_id,
    )


async def issue(
    db: AsyncSession, approval: Approval, product_ids: list[int], *, user_id: int | None
) -> None:
    """
    Let the pieces out.

    Each one has to be genuinely on the shelf at the issuing branch. A piece
    already out on another memo, already sold, or sitting in another shop is
    refused rather than corrected — every one of those means the counter is
    describing something that did not happen.
    """
    if not product_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A memo needs at least one piece on it.",
        )
    if len(set(product_ids)) != len(product_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The same piece appears twice on this memo.",
        )

    for pid in product_ids:
        product = await db.get(Product, pid)
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product #{pid} not found")
        if product.status is not ProductStatus.in_stock:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{product.serial_no} is {product.status.value.replace('_', ' ')} and cannot go "
                "out on approval.",
            )
        if product.branch_id != approval.branch_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{product.serial_no} is held at "
                f"{product.branch.name if product.branch else 'another branch'}, not "
                f"{approval.branch.name}.",
            )

        db.add(
            ApprovalItem(
                approval_id=approval.id,
                product_id=product.id,
                status=ApprovalLineStatus.out,
            )
        )
        product.status = ProductStatus.on_approval
        await _move(
            db, product,
            type=MovementType.approval_out,
            delta=-1,
            approval=approval,
            note=f"{approval.approval_no} to {approval.customer.name}",
            user_id=user_id,
        )

    approval.status = ApprovalStatus.out
    approval.issued_at = datetime.now(timezone.utc)
    approval.issued_by_id = user_id
    await db.flush()


async def return_lines(
    db: AsyncSession, approval: Approval, line_ids: list[int], *, user_id: int | None
) -> int:
    """Take pieces back onto the shelf. Returns how many actually moved."""
    by_id = {i.id: i for i in await lines_of(db, approval)}
    moved = 0
    for lid in line_ids:
        line = by_id.get(lid)
        if line is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Line #{lid} is not on {approval.approval_no}."
            )
        if line.status is not ApprovalLineStatus.out:
            # Already settled. Skipped rather than refused: a counter hand
            # ticking every box on a memo where one piece was billed yesterday
            # is describing what is in front of them, not making a mistake.
            continue
        product = await db.get(Product, line.product_id)
        if product is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The piece on line #{lid} no longer exists, so it cannot be returned to stock.",
            )
        line.status = ApprovalLineStatus.returned
        line.returned_at = datetime.now(timezone.utc)
        product.status = ProductStatus.in_stock
        await _move(
            db, product,
            type=MovementType.approval_return_in,
            delta=1,
            approval=approval,
            note=f"{approval.approval_no} returned",
            user_id=user_id,
        )
        moved += 1

    await db.flush()
    refresh_status(approval, await lines_of(db, approval))
    await db.flush()
    return moved


async def mark_sold(
    db: AsyncSession,
    approval: Approval,
    line_ids: list[int],
    *,
    invoice_id: int | None,
    user_id: int | None,
) -> int:
    """
    The customer is keeping these.

    The piece does not come back to stock — it is sold — so no return movement
    is posted. The invoice that bills it does the stock and ledger work, which
    is why this only records the link.
    """
    by_id = {i.id: i for i in await lines_of(db, approval)}
    marked = 0
    for lid in line_ids:
        line = by_id.get(lid)
        if line is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Line #{lid} is not on {approval.approval_no}."
            )
        if line.status is not ApprovalLineStatus.out:
            continue
        line.status = ApprovalLineStatus.sold
        line.invoice_id = invoice_id
        marked += 1

    await db.flush()
    refresh_status(approval, await lines_of(db, approval))
    await db.flush()
    return marked


def refresh_status(approval: Approval, lines: list[ApprovalItem]) -> None:
    """
    Recompute the memo's own state from its lines.

    Derived rather than set by each caller, so a memo can never claim to be
    closed while a piece is still out — which is the one thing this document
    exists to prevent. Lines are passed in rather than read off the
    relationship, which may be stale within a session that has just written to
    it.
    """
    if approval.status is ApprovalStatus.cancelled:
        return
    still_out = sum(1 for i in lines if i.status is ApprovalLineStatus.out)
    settled = sum(1 for i in lines if i.status is not ApprovalLineStatus.out)
    if still_out == 0 and lines:
        approval.status = ApprovalStatus.closed
        approval.closed_at = datetime.now(timezone.utc)
    elif settled:
        approval.status = ApprovalStatus.partly_returned
        approval.closed_at = None
    else:
        approval.status = ApprovalStatus.out
        approval.closed_at = None


async def cancel(
    db: AsyncSession, approval: Approval, *, reason: str, user_id: int | None
) -> None:
    """
    Abandon the memo and put everything still out back on the shelf.

    Anything else would leave pieces marked `on_approval` against a document
    nobody is chasing — stock that exists, is not sellable, and has no owner.
    """
    if approval.status is ApprovalStatus.cancelled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{approval.approval_no} is already cancelled."
        )
    out = [i.id for i in await lines_of(db, approval) if i.status is ApprovalLineStatus.out]
    if out:
        await return_lines(db, approval, out, user_id=user_id)
    approval.status = ApprovalStatus.cancelled
    approval.cancelled_reason = reason
    approval.closed_at = datetime.now(timezone.utc)
    await db.flush()
