"""
Memos: pieces let out on approval, and getting them back.

The document exists to answer one question the shelf cannot — where is that
piece, and who has had it since when. Nothing here posts to the ledger: no sale
has happened, and booking one on a memo records revenue that may never arrive.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.core import clock
from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.approval import (
    Approval,
    ApprovalItem,
    ApprovalLineStatus,
    ApprovalStatus,
)
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.product import Product
from app.schemas.approval import (
    ApprovalBoard,
    ApprovalCancel,
    ApprovalCreate,
    ApprovalItemRead,
    ApprovalLines,
    ApprovalRead,
    ApprovalSold,
)
from app.services import approvals as svc
from app.services import branches
from app.services.audit import log_action
from app.services.ledger import d

router = APIRouter()
read = Depends(require_perm("approval:read"))
write = Depends(require_perm("approval:write"))

OPEN_STATUSES = (ApprovalStatus.out, ApprovalStatus.partly_returned)


def _overdue(a: Approval) -> int | None:
    if a.due_date is None or a.status not in OPEN_STATUSES:
        return None
    days = (clock.today() - a.due_date).days
    return days if days > 0 else None


async def _item_read(db: DbSession, i: ApprovalItem) -> ApprovalItemRead:
    product = await db.get(Product, i.product_id)
    return ApprovalItemRead(
        id=i.id,
        created_at=i.created_at,
        updated_at=i.updated_at,
        approval_id=i.approval_id,
        product_id=i.product_id,
        product_serial=product.serial_no if product else None,
        product_name=product.name if product else None,
        gold_weight_g=d(product.gold_weight_g) if product else None,
        status=i.status,
        returned_at=i.returned_at,
        invoice_id=i.invoice_id,
        notes=i.notes,
    )


async def _read(db: DbSession, a: Approval) -> ApprovalRead:
    items = [await _item_read(db, i) for i in a.items]
    return ApprovalRead(
        id=a.id,
        created_at=a.created_at,
        updated_at=a.updated_at,
        approval_no=a.approval_no,
        customer_id=a.customer_id,
        customer_name=a.customer.name if a.customer else None,
        customer_phone=a.customer.phone if a.customer else None,
        branch_id=a.branch_id,
        branch_name=a.branch.name if a.branch else None,
        status=a.status,
        issued_at=a.issued_at,
        due_date=a.due_date,
        closed_at=a.closed_at,
        days_overdue=_overdue(a),
        out_count=sum(1 for i in a.items if i.status is ApprovalLineStatus.out),
        total_count=len(a.items),
        notes=a.notes,
        cancelled_reason=a.cancelled_reason,
        items=items,
    )


async def _get(db: DbSession, approval_id: int) -> Approval:
    a = await db.get(Approval, approval_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memo not found")
    return a


@router.post("", response_model=ApprovalRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create(payload: ApprovalCreate, db: DbSession, current: CurrentUser) -> ApprovalRead:
    """Let pieces out on approval."""
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    branch = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)

    approval = Approval(
        approval_no=await svc.next_approval_no(db),
        customer_id=customer.id,
        branch_id=branch.id,
        status=ApprovalStatus.out,
        due_date=payload.due_date,
        notes=payload.notes,
    )
    db.add(approval)
    await db.flush()
    # Loaded onto the instance so the service can name them in movement notes
    # without lazy-loading, which async SQLAlchemy refuses.
    approval.customer = customer
    approval.branch = branch

    await svc.issue(db, approval, payload.product_ids, user_id=current.id)
    await log_action(
        db, user=current,
        action="approval.create",
        resource_type="approval", resource_id=approval.id,
        details={
            "approval_no": approval.approval_no,
            "customer": customer.name,
            "pieces": len(payload.product_ids),
            "due": str(payload.due_date) if payload.due_date else None,
        },
    )
    await db.commit()
    await db.refresh(approval)
    return await _read(db, approval)


@router.get("", response_model=list[ApprovalRead], dependencies=[read])
async def list_approvals(
    db: DbSession,
    status_: ApprovalStatus | None = Query(default=None, alias="status"),
    customer_id: int | None = Query(default=None),
    branch_id: int | None = Query(default=None),
    open_only: bool = Query(default=False),
    overdue: bool = Query(default=False),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ApprovalRead]:
    stmt = select(Approval).order_by(Approval.id.desc()).limit(limit).offset(offset)
    if status_:
        stmt = stmt.where(Approval.status == status_)
    if customer_id is not None:
        stmt = stmt.where(Approval.customer_id == customer_id)
    if branch_id is not None:
        stmt = stmt.where(Approval.branch_id == branch_id)
    if open_only or overdue:
        stmt = stmt.where(Approval.status.in_(OPEN_STATUSES))
    if overdue:
        stmt = stmt.where(Approval.due_date.is_not(None), Approval.due_date < clock.today())
    if q:
        stmt = stmt.where(Approval.approval_no.ilike(f"%{q}%"))
    rows = list((await db.execute(stmt)).scalars().all())
    return [await _read(db, a) for a in rows]


@router.get("/board", response_model=ApprovalBoard, dependencies=[read])
async def board(db: DbSession) -> ApprovalBoard:
    """What is out right now — the number a shop wants on a dashboard."""
    counts = dict(
        (
            await db.execute(
                select(Approval.status, func.count(Approval.id)).group_by(Approval.status)
            )
        ).all()
    )
    overdue = (
        await db.execute(
            select(func.count(Approval.id)).where(
                Approval.status.in_(OPEN_STATUSES),
                Approval.due_date.is_not(None),
                Approval.due_date < clock.today(),
            )
        )
    ).scalar_one()
    pieces = (
        await db.execute(
            select(func.count(ApprovalItem.id)).where(
                ApprovalItem.status == ApprovalLineStatus.out
            )
        )
    ).scalar_one()
    return ApprovalBoard(
        out=int(counts.get(ApprovalStatus.out, 0)),
        partly_returned=int(counts.get(ApprovalStatus.partly_returned, 0)),
        overdue=int(overdue),
        pieces_out=int(pieces),
    )


@router.get("/{approval_id}", response_model=ApprovalRead, dependencies=[read])
async def get_approval(approval_id: int, db: DbSession) -> ApprovalRead:
    return await _read(db, await _get(db, approval_id))


@router.post("/{approval_id}/return", response_model=ApprovalRead, dependencies=[write])
async def return_pieces(
    approval_id: int, payload: ApprovalLines, db: DbSession, current: CurrentUser
) -> ApprovalRead:
    """Take pieces back onto the shelf."""
    approval = await _get(db, approval_id)
    moved = await svc.return_lines(db, approval, payload.line_ids, user_id=current.id)
    await log_action(
        db, user=current,
        action="approval.return",
        resource_type="approval", resource_id=approval.id,
        details={"approval_no": approval.approval_no, "returned": moved},
    )
    await db.commit()
    await db.refresh(approval)
    return await _read(db, approval)


@router.post("/{approval_id}/sold", response_model=ApprovalRead, dependencies=[write])
async def keep_pieces(
    approval_id: int, payload: ApprovalSold, db: DbSession, current: CurrentUser
) -> ApprovalRead:
    """
    The customer is keeping these.

    Records the decision and the invoice that bills it. The stock and ledger
    work belongs to that invoice, not here — a memo that moved money would be
    a second, weaker sales path.
    """
    approval = await _get(db, approval_id)
    if payload.invoice_id is not None and await db.get(Invoice, payload.invoice_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    marked = await svc.mark_sold(
        db, approval, payload.line_ids, invoice_id=payload.invoice_id, user_id=current.id
    )
    await log_action(
        db, user=current,
        action="approval.sold",
        resource_type="approval", resource_id=approval.id,
        details={
            "approval_no": approval.approval_no,
            "kept": marked,
            "invoice_id": payload.invoice_id,
        },
    )
    await db.commit()
    await db.refresh(approval)
    return await _read(db, approval)


@router.post(
    "/{approval_id}/cancel",
    response_model=ApprovalRead,
    # Cancelling puts every piece still out back on the shelf. That is a real
    # stock movement on goods the shop cannot currently see, so it re-authenticates.
    dependencies=[write, Depends(require_password_confirm)],
)
async def cancel_approval(
    approval_id: int, payload: ApprovalCancel, db: DbSession, current: CurrentUser
) -> ApprovalRead:
    approval = await _get(db, approval_id)
    await svc.cancel(db, approval, reason=payload.reason, user_id=current.id)
    await log_action(
        db, user=current,
        action="approval.cancel",
        resource_type="approval", resource_id=approval.id,
        details={"approval_no": approval.approval_no, "reason": payload.reason},
    )
    await db.commit()
    await db.refresh(approval)
    return await _read(db, approval)
