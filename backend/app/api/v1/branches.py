"""
Branches, and the goods that move between them.

Branch CRUD is deliberately not generated from the masters factory: a branch is
not inert reference data. Promoting one to default changes where every unscoped
row lands, closing one has to be refused while it still holds stock, and both
are decisions that deserve to be spelled out rather than inherited.

Transfers follow the same shape as a job leg — issue, then receive, with the
goods provably somewhere in between — because that is the shape of the real
event and the shop already reads it that way.
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.branch import (
    Branch,
    BranchTransfer,
    BranchTransferItem,
    TransferStatus,
)
from app.models.inventory import InventoryItem, InventoryType
from app.models.location import City
from app.models.product import Product, ProductStatus
from app.schemas.branch import (
    BranchCreate,
    BranchRead,
    BranchStock,
    BranchUpdate,
    TransferCancel,
    TransferCreate,
    TransferLineRead,
    TransferRead,
)
from app.services import branches as svc
from app.services.audit import log_action
from app.services.ledger import d
from app.services.storage import StorageError, get_storage, read_image_upload

router = APIRouter()
# Transfers get their own router rather than sitting under /branches/…, so that
# `/transfers/{id}` cannot be shadowed by `/branches/{branch_id}` — FastAPI
# matches in declaration order and a document id is not a branch id.
transfers_router = APIRouter()
read = Depends(require_perm("branch:read"))
write = Depends(require_perm("branch:write"))
transfer_read = Depends(require_perm("transfer:read"))
transfer_write = Depends(require_perm("transfer:write"))


def _branch_read(b: Branch) -> BranchRead:
    return BranchRead(
        id=b.id,
        created_at=b.created_at,
        updated_at=b.updated_at,
        code=b.code,
        name=b.name,
        phone=b.phone,
        address=b.address,
        city_id=b.city_id,
        city_name=b.city.name if b.city else None,
        is_active=b.is_active,
        is_default=b.is_default,
        letterhead_name=b.letterhead_name,
        tagline=b.tagline,
        logo_url=b.logo_url,
        print_name=b.print_name,
        notes=b.notes,
    )


def _line_read(line: BranchTransferItem, product: Product | None, inv: InventoryItem | None):
    return TransferLineRead(
        id=line.id,
        created_at=line.created_at,
        updated_at=line.updated_at,
        transfer_id=line.transfer_id,
        product_id=line.product_id,
        product_serial=product.serial_no if product else None,
        product_name=product.name if product else None,
        inventory_item_id=line.inventory_item_id,
        inventory_label=inv.label if inv else None,
        quantity=line.quantity,
        weight_g=d(line.weight_g),
        weight_ct=d(line.weight_ct),
        purity=line.purity,
        received_inventory_item_id=line.received_inventory_item_id,
        notes=line.notes,
    )


async def _transfer_read(db: DbSession, t: BranchTransfer) -> TransferRead:
    lines = []
    for line in t.items:
        product = await db.get(Product, line.product_id) if line.product_id else None
        inv = (
            await db.get(InventoryItem, line.inventory_item_id)
            if line.inventory_item_id
            else None
        )
        lines.append(_line_read(line, product, inv))
    return TransferRead(
        id=t.id,
        created_at=t.created_at,
        updated_at=t.updated_at,
        transfer_no=t.transfer_no,
        from_branch_id=t.from_branch_id,
        from_branch_name=t.from_branch.name if t.from_branch else None,
        to_branch_id=t.to_branch_id,
        to_branch_name=t.to_branch.name if t.to_branch else None,
        status=t.status,
        sent_at=t.sent_at,
        received_at=t.received_at,
        sent_by_id=t.sent_by_id,
        received_by_id=t.received_by_id,
        notes=t.notes,
        lines=lines,
    )


async def _get_branch(db: DbSession, branch_id: int) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    return branch


async def _clear_other_defaults(db: DbSession, keep_id: int | None) -> None:
    """
    Demote whichever branch currently holds the flag.

    A unique partial index refuses two defaults, so this has to run *before*
    the new one is set or the write fails on the constraint rather than doing
    what the caller asked.
    """
    stmt = select(Branch).where(Branch.is_default.is_(True))
    if keep_id is not None:
        stmt = stmt.where(Branch.id != keep_id)
    for other in (await db.execute(stmt)).scalars().all():
        other.is_default = False
    await db.flush()


# --------------------------------------------------------------------- branches


@router.post("", response_model=BranchRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_branch(payload: BranchCreate, db: DbSession, current: CurrentUser) -> BranchRead:
    if payload.city_id is not None and await db.get(City, payload.city_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "City not found")

    branch = Branch(**payload.model_dump(exclude={"is_default"}), is_default=False)
    db.add(branch)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A branch with code {payload.code} or name {payload.name} already exists.",
        ) from exc

    if payload.is_default:
        await _clear_other_defaults(db, keep_id=branch.id)
        branch.is_default = True

    await log_action(
        db, user=current,
        action="branch.create",
        resource_type="branch", resource_id=branch.id,
        details={"code": branch.code, "name": branch.name, "is_default": branch.is_default},
    )
    await db.commit()
    await db.refresh(branch)
    return _branch_read(branch)


@router.get("", response_model=list[BranchRead], dependencies=[read])
async def list_branches(
    db: DbSession,
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None),
) -> list[BranchRead]:
    stmt = select(Branch).order_by(Branch.is_default.desc(), Branch.name)
    if is_active is not None:
        stmt = stmt.where(Branch.is_active.is_(is_active))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Branch.name.ilike(like) | Branch.code.ilike(like))
    return [_branch_read(b) for b in (await db.execute(stmt)).scalars().all()]


@router.get("/stock", response_model=list[BranchStock], dependencies=[read])
async def branch_stock(db: DbSession) -> list[BranchStock]:
    """
    What each branch is holding, in one query per measure.

    Assembled here rather than left to the client because the branch list is
    unreadable without it — "three shops" tells an owner nothing, "three shops
    and where the metal is" tells them everything.
    """
    products = dict(
        (
            await db.execute(
                select(Product.branch_id, func.count(Product.id))
                .where(Product.status == ProductStatus.in_stock)
                .group_by(Product.branch_id)
            )
        ).all()
    )
    gold = dict(
        (
            await db.execute(
                select(InventoryItem.branch_id, func.coalesce(func.sum(InventoryItem.weight_g), 0))
                .where(InventoryItem.type == InventoryType.raw_gold)
                .group_by(InventoryItem.branch_id)
            )
        ).all()
    )
    stones = dict(
        (
            await db.execute(
                select(InventoryItem.branch_id, func.coalesce(func.sum(InventoryItem.weight_ct), 0))
                .where(InventoryItem.type == InventoryType.raw_stone)
                .group_by(InventoryItem.branch_id)
            )
        ).all()
    )
    rows = (await db.execute(select(Branch.id).order_by(Branch.id))).scalars().all()
    return [
        BranchStock(
            branch_id=bid,
            products_in_stock=int(products.get(bid, 0)),
            gold_g=d(gold.get(bid, 0)),
            stone_ct=d(stones.get(bid, 0)),
        )
        for bid in rows
    ]


@router.get("/{branch_id}", response_model=BranchRead, dependencies=[read])
async def get_branch(branch_id: int, db: DbSession) -> BranchRead:
    return _branch_read(await _get_branch(db, branch_id))


@router.patch("/{branch_id}", response_model=BranchRead, dependencies=[write])
async def update_branch(
    branch_id: int, payload: BranchUpdate, db: DbSession, current: CurrentUser
) -> BranchRead:
    branch = await _get_branch(db, branch_id)
    data = payload.model_dump(exclude_unset=True)

    if data.get("city_id") is not None and await db.get(City, data["city_id"]) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "City not found")

    # Closing a branch that still holds goods would strand them: they belong to
    # a shop nobody can select any more, and no report would show them.
    if data.get("is_active") is False and branch.is_active:
        held = (
            await db.execute(
                select(func.count(Product.id)).where(
                    Product.branch_id == branch.id, Product.status == ProductStatus.in_stock
                )
            )
        ).scalar_one()
        if held:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{branch.name} still holds {held} piece(s) in stock. Transfer them to another "
                "branch before closing it.",
            )
        if branch.is_default:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{branch.name} is the default branch. Make another branch the default first.",
            )

    becoming_default = data.pop("is_default", None)
    if becoming_default is False and branch.is_default:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A business needs one default branch. Promote another branch instead of clearing "
            "this one.",
        )

    for field, value in data.items():
        setattr(branch, field, value)

    if becoming_default:
        await _clear_other_defaults(db, keep_id=branch.id)
        branch.is_default = True

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another branch already uses that code or name."
        ) from exc

    await log_action(
        db, user=current,
        action="branch.update",
        resource_type="branch", resource_id=branch.id,
        details={k: str(v) for k, v in data.items()} | (
            {"is_default": True} if becoming_default else {}
        ),
    )
    await db.commit()
    await db.refresh(branch)
    return _branch_read(branch)


@router.post("/{branch_id}/logo", response_model=BranchRead, dependencies=[write])
async def upload_logo(
    branch_id: int,
    db: DbSession,
    current: CurrentUser,
    file: UploadFile = File(...),
) -> BranchRead:
    """
    The mark that heads the shop's printed documents.

    Same acceptance rules as a product photograph, and the same ordering: the
    row is pointed at the new object before the old one is swept, so a failure
    leaves an orphaned file rather than a letterhead with a broken image.
    """
    branch = await _get_branch(db, branch_id)
    contents, ext = await read_image_upload(file)

    storage = get_storage()
    previous_url = branch.logo_url
    fname = f"branch_{branch_id}_{uuid.uuid4().hex}{ext}"
    try:
        logo_url = await run_in_threadpool(storage.save, contents, filename=fname)
    except StorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    branch.logo_url = logo_url
    await log_action(
        db, user=current,
        action="branch.logo",
        resource_type="branch", resource_id=branch.id,
        details={"branch": branch.name},
    )
    await db.commit()
    await db.refresh(branch)

    if previous_url and previous_url != logo_url:
        await run_in_threadpool(storage.delete, previous_url)

    return _branch_read(branch)


# -------------------------------------------------------------------- transfers


@transfers_router.post(
    "",
    response_model=TransferRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[transfer_write],
)
async def create_transfer(
    payload: TransferCreate, db: DbSession, current: CurrentUser
) -> TransferRead:
    """Draft a transfer. Nothing moves until it is sent."""
    source = await _get_branch(db, payload.from_branch_id)
    dest = await _get_branch(db, payload.to_branch_id)
    if not dest.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{dest.name} is closed and cannot receive goods."
        )

    transfer = BranchTransfer(
        transfer_no=await svc.next_transfer_no(db),
        from_branch=source,
        to_branch=dest,
        status=TransferStatus.draft,
        notes=payload.notes,
    )
    db.add(transfer)
    await db.flush()

    for line in payload.lines:
        db.add(
            BranchTransferItem(
                transfer_id=transfer.id,
                product_id=line.product_id,
                inventory_item_id=line.inventory_item_id,
                quantity=line.quantity,
                weight_g=line.weight_g,
                weight_ct=line.weight_ct,
                purity=line.purity,
                notes=line.notes,
            )
        )
    await db.flush()
    await db.refresh(transfer)

    await log_action(
        db, user=current,
        action="transfer.create",
        resource_type="branch_transfer", resource_id=transfer.id,
        details={
            "transfer_no": transfer.transfer_no,
            "from": source.name,
            "to": dest.name,
            "lines": len(payload.lines),
        },
    )
    await db.commit()
    await db.refresh(transfer)
    return await _transfer_read(db, transfer)


@transfers_router.get("", response_model=list[TransferRead], dependencies=[transfer_read])
async def list_transfers(
    db: DbSession,
    status_: TransferStatus | None = Query(default=None, alias="status"),
    branch_id: int | None = Query(default=None, description="Either end of the move"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TransferRead]:
    stmt = (
        select(BranchTransfer).order_by(BranchTransfer.id.desc()).limit(limit).offset(offset)
    )
    if status_:
        stmt = stmt.where(BranchTransfer.status == status_)
    if branch_id is not None:
        stmt = stmt.where(
            (BranchTransfer.from_branch_id == branch_id)
            | (BranchTransfer.to_branch_id == branch_id)
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [await _transfer_read(db, t) for t in rows]


async def _get_transfer(db: DbSession, transfer_id: int) -> BranchTransfer:
    t = await db.get(BranchTransfer, transfer_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer not found")
    return t


@transfers_router.get("/{transfer_id}", response_model=TransferRead, dependencies=[transfer_read])
async def get_transfer(transfer_id: int, db: DbSession) -> TransferRead:
    return await _transfer_read(db, await _get_transfer(db, transfer_id))


@transfers_router.post(
    "/{transfer_id}/send", response_model=TransferRead, dependencies=[transfer_write]
)
async def send_transfer(transfer_id: int, db: DbSession, current: CurrentUser) -> TransferRead:
    transfer = await _get_transfer(db, transfer_id)
    await svc.send(db, transfer, user_id=current.id)
    await log_action(
        db, user=current,
        action="transfer.send",
        resource_type="branch_transfer", resource_id=transfer.id,
        details={"transfer_no": transfer.transfer_no, "lines": len(transfer.items)},
    )
    await db.commit()
    await db.refresh(transfer)
    return await _transfer_read(db, transfer)


@transfers_router.post(
    "/{transfer_id}/receive", response_model=TransferRead, dependencies=[transfer_write]
)
async def receive_transfer(transfer_id: int, db: DbSession, current: CurrentUser) -> TransferRead:
    transfer = await _get_transfer(db, transfer_id)
    await svc.receive(db, transfer, user_id=current.id)
    await log_action(
        db, user=current,
        action="transfer.receive",
        resource_type="branch_transfer", resource_id=transfer.id,
        details={"transfer_no": transfer.transfer_no},
    )
    await db.commit()
    await db.refresh(transfer)
    return await _transfer_read(db, transfer)


@transfers_router.post(
    "/{transfer_id}/cancel",
    response_model=TransferRead,
    # Cancelling a sent transfer puts stock back on the sending branch's shelf.
    # That is a real movement, so the caller re-authenticates.
    dependencies=[transfer_write, Depends(require_password_confirm)],
)
async def cancel_transfer(
    transfer_id: int, payload: TransferCancel, db: DbSession, current: CurrentUser
) -> TransferRead:
    transfer = await _get_transfer(db, transfer_id)
    await svc.cancel(db, transfer, reason=payload.reason, user_id=current.id)
    await log_action(
        db, user=current,
        action="transfer.cancel",
        resource_type="branch_transfer", resource_id=transfer.id,
        details={"transfer_no": transfer.transfer_no, "reason": payload.reason},
    )
    await db.commit()
    await db.refresh(transfer)
    return await _transfer_read(db, transfer)
