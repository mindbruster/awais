import uuid

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.approval import Approval, ApprovalItem
from app.models.branch import BranchTransfer, BranchTransferItem
from app.models.customer import Customer
from app.models.department import Department
from app.models.design import Design, JobLeg, LegStatus
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from app.models.product import Product, ProductStatus
from app.models.vendor import Vendor
from app.schemas.product import (
    GeneratedImageRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.services import branches, image_gen
from app.services.audit import changes, log_action, snapshot
from app.services.serial import next_product_serial
from app.schemas.timeline import ProductTimeline, TimelineEvent
from app.services.ledger import d
from app.services.storage import StorageError, get_storage, read_image_upload

router = APIRouter()
read = Depends(require_perm("product:read"))
write = Depends(require_perm("product:write"))
delete = Depends(require_perm("product:delete"))



@router.get("", response_model=list[ProductRead], dependencies=[read])
async def list_products(
    db: DbSession,
    q: str | None = Query(default=None),
    branch_id: int | None = Query(default=None, description="Pieces sitting at this shop"),
    status: ProductStatus | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Product]:
    stmt = select(Product).order_by(Product.id.desc()).limit(limit).offset(offset)
    if branch_id is not None:
        stmt = stmt.where(Product.branch_id == branch_id)
    if status is not None:
        stmt = stmt.where(Product.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Product.serial_no.ilike(like), Product.name.ilike(like), Product.category.ilike(like))
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_product(
    payload: ProductCreate, db: DbSession, current: CurrentUser
) -> Product:
    data = payload.model_dump()
    if not data.get("serial_no"):
        data["serial_no"] = await next_product_serial(db)
    # A piece sits in a showroom. Resolved rather than required, so a
    # single-shop business never has to state the obvious.
    branch = await branches.resolve_branch(
        db, requested_id=data.pop("branch_id", None), user=current
    )
    product = Product(**data)
    product.branch_id = branch.id
    db.add(product)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "serial_no already exists") from exc
    await db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductRead, dependencies=[read])
async def get_product(product_id: int, db: DbSession) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductRead, dependencies=[write])
async def update_product(
    product_id: int, payload: ProductUpdate, db: DbSession, current: CurrentUser
) -> Product:
    """
    Edit a piece.

    Audited field by field, because the things editable here — weight, purity,
    cost, price — are what the piece is worth. An unlogged correction to a
    22k weight is indistinguishable from metal going missing.
    """
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    was = snapshot(product)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(product, k, v)
    before, after = changes(was, snapshot(product))
    try:
        if before or after:
            await log_action(
                db,
                user=current,
                action="product.update",
                resource_type="product",
                resource_id=product.id,
                before=before,
                after=after,
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "serial_no already exists") from exc
    await db.refresh(product)
    return product


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[delete, Depends(require_password_confirm)],
)
async def delete_product(product_id: int, db: DbSession, current: CurrentUser) -> None:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    # Capture the image URL before delete so we can sweep it once the row is gone.
    image_url = product.image_url

    await log_action(
        db, user=current,
        action="product.delete",
        resource_type="product", resource_id=product.id,
        details={"serial_no": product.serial_no, "name": product.name},
        before=snapshot(product),
    )
    await db.delete(product)
    await db.commit()

    # Best-effort sweep. The backend swallows a missing or foreign object: the
    # row is already gone and the delete must not fail after the fact.
    if image_url:
        await run_in_threadpool(get_storage().delete, image_url)


@router.post("/{product_id}/image", response_model=ProductRead, dependencies=[write])
async def upload_image(
    product_id: int,
    db: DbSession,
    file: UploadFile = File(...),
) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    contents, ext = await read_image_upload(file)

    storage = get_storage()
    previous_url = product.image_url
    fname = f"product_{product_id}_{uuid.uuid4().hex}{ext}"

    # Both backends are blocking (a disk write, or an HTTPS PUT to the bucket),
    # so keep them off the event loop.
    try:
        image_url = await run_in_threadpool(storage.save, contents, filename=fname)
    except StorageError as exc:
        # The bucket being unreachable is an infrastructure fault, not a bad
        # request — say so, and say which backend failed.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    # Store the new URL first. If the commit fails the fresh object is orphaned,
    # which is recoverable; losing the row's pointer to a photograph is not.
    product.image_url = image_url
    await db.commit()
    await db.refresh(product)

    # Replacing a photo used to leak the old file forever. Sweep it now that the
    # row no longer references it.
    if previous_url and previous_url != image_url:
        await run_in_threadpool(storage.delete, previous_url)

    return product


@router.post(
    "/{product_id}/image/generate",
    response_model=GeneratedImageRead,
    # Not `write`: uploading a photograph and commissioning a drawing are
    # different acts. The first is free and part of counter work; the second
    # bills the shop per call.
    dependencies=[Depends(require_perm("ai:image"))],
)
async def generate_product_image(
    product_id: int,
    db: DbSession,
    current: CurrentUser,
    prompt: str = Form(..., min_length=3, max_length=2000),
    attach: bool = Form(default=False),
    references: list[UploadFile] = File(default=[]),
) -> GeneratedImageRead:
    """
    Draw a proposal for this piece, optionally guided by photographs.

    `attach=false` by default, and that default is the point: the picture is
    stored and handed back so somebody can look at it, and only becomes the
    product's image when they say so. Drawing straight over a photograph of the
    real finished article — which is what an attach-by-default would do on the
    second attempt — replaces a record with an illustration.

    Costs money per call, so nothing reaches here except by someone pressing the
    button. There is no generate-on-save anywhere.
    """
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    refs: list[tuple[bytes, str]] = []
    for upload in references[: image_gen.MAX_REFERENCES]:
        media_type = (upload.content_type or "").lower()
        if media_type not in image_gen.ALLOWED_REFERENCE_TYPES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"Reference images must be one of "
                f"{', '.join(sorted(image_gen.ALLOWED_REFERENCE_TYPES))}; got "
                f"{media_type or 'unknown'}.",
            )
        # Same chunked read as the upload endpoint, for the same reason: measure
        # as it arrives rather than allocating the whole body to find its size.
        chunks: list[bytes] = []
        total = 0
        while chunk := await upload.read(64 * 1024):
            total += len(chunk)
            if total > image_gen.MAX_REFERENCE_BYTES:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"Reference images are limited to "
                    f"{image_gen.MAX_REFERENCE_BYTES // (1024 * 1024)}MB each.",
                )
            chunks.append(chunk)
        if chunks:
            refs.append((b"".join(chunks), media_type))

    generated = await image_gen.generate(prompt, references=refs)

    storage = get_storage()
    fname = f"product_{product_id}_gen_{uuid.uuid4().hex}{generated.extension}"
    try:
        url = await run_in_threadpool(storage.save, generated.data, filename=fname)
    except StorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    previous_url = product.image_url
    if attach:
        product.image_url = url
        await db.commit()
        await db.refresh(product)

    await log_action(
        db,
        user_id=current.id,
        action="product.image_generate",
        resource_type="product",
        resource_id=product_id,
        # The prompt is kept because an image that misrepresents a piece to a
        # customer is a real dispute, and the first question is what was asked
        # for. The reference photographs are not stored — only how many.
        details={
            "prompt": prompt[:500],
            "references": len(refs),
            "model": generated.model,
            "attached": attach,
        },
    )
    await db.commit()

    # Only sweep the old file once the row is committed away from it, and never
    # when it was a real photograph the operator did not ask to replace.
    if attach and previous_url and previous_url != url:
        await run_in_threadpool(storage.delete, previous_url)

    return GeneratedImageRead(
        image_url=url, model=generated.model, attached=attach, references_used=len(refs)
    )


@router.get("/{product_id}/timeline", response_model=ProductTimeline, dependencies=[read])
async def product_timeline(product_id: int, db: DbSession) -> ProductTimeline:
    """
    Everything that happened to one piece, in order.

    Assembled from the documents rather than from a log: the job that made it,
    every leg of that job, the stocking, any transfer between shops, memos it
    went out on, and the bill that finally sold it. Nothing here is stored — a
    stored timeline is a second version of history that drifts from the first
    the moment anything is reversed.

    Events with no date sort last rather than first. A leg still out with a
    worker has no received date, and treating a missing timestamp as the epoch
    would put it before the metal was even bought.
    """
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    events: list[TimelineEvent] = []
    design: Design | None = None

    if product.design_id:
        design = (
            await db.execute(
                select(Design)
                .options(selectinload(Design.legs).selectinload(JobLeg.stones))
                .where(Design.id == product.design_id)
            )
        ).unique().scalar_one_or_none()

    if design is not None:
        events.append(
            TimelineEvent(
                kind="job",
                title=f"Job {design.design_no} opened",
                detail=f"{design.item.name} · {design.status.value}"
                if getattr(design, "item", None)
                else design.status.value,
                at=design.created_at,
                reference=design.design_no,
                to=f"/designs/{design.id}",
            )
        )

        workers = {
            int(w.id): w.name
            for w in (
                (
                    await db.execute(
                        select(Vendor).where(
                            Vendor.id.in_([l.worker_id for l in design.legs if l.worker_id])
                        )
                    )
                )
                .unique()
                .scalars()
                .all()
            )
        } if any(l.worker_id for l in design.legs) else {}
        depts = {
            int(dp.id): dp.name
            for dp in (
                (await db.execute(select(Department))).unique().scalars().all()
            )
        }

        for leg in design.legs:
            who = workers.get(leg.worker_id or -1) or depts.get(leg.department_id or -1) or "the bench"
            stage = depts.get(leg.department_id or -1)
            issued_ct = sum((d(s.weight_issued_ct) for s in leg.stones), Decimal("0"))
            events.append(
                TimelineEvent(
                    kind="issued",
                    title=f"Issued to {who}",
                    detail=" · ".join(
                        x
                        for x in [
                            stage,
                            f"{d(leg.gold_issued_g)} g"
                            + (f" {leg.gold_issued_purity}k" if leg.gold_issued_purity else ""),
                            f"{issued_ct} ct of stones" if issued_ct else None,
                            "his own metal" if d(leg.gold_issued_g) == 0 else None,
                        ]
                        if x
                    ),
                    at=leg.issued_at,
                    reference=design.design_no,
                    to=f"/designs/{design.id}",
                    weight_g=d(leg.gold_issued_g),
                    stone_ct=issued_ct or None,
                    tone="warn" if leg.status is LegStatus.issued else "plain",
                )
            )
            if leg.status is LegStatus.received:
                excess = d(leg.wastage_excess_g)
                set_ct = sum((d(s.weight_set_ct) for s in leg.stones), Decimal("0"))
                events.append(
                    TimelineEvent(
                        kind="received",
                        title=f"Received from {who}",
                        detail=" · ".join(
                            x
                            for x in [
                                f"{d(leg.gold_received_g)} g back"
                                + (
                                    f" (gross {d(leg.gold_received_gross_g)})"
                                    if d(leg.gold_received_gross_g) != d(leg.gold_received_g)
                                    else ""
                                ),
                                f"{set_ct} ct set" if set_ct else None,
                                f"{d(leg.wastage_allowed_g)} g allowed",
                                f"{excess} g owed" if excess > 0 else "within allowance",
                                f"labour {d(leg.labour_amount)}" if d(leg.labour_amount) else None,
                            ]
                            if x
                        ),
                        at=leg.received_at,
                        reference=design.design_no,
                        to=f"/designs/{design.id}",
                        weight_g=d(leg.gold_received_g),
                        stone_ct=set_ct or None,
                        amount=d(leg.labour_amount) or None,
                        tone="bad" if excess > 0 else "good",
                    )
                )

    events.append(
        TimelineEvent(
            kind="stocked",
            title=f"Entered stock as {product.serial_no}",
            detail=" · ".join(
                x
                for x in [
                    f"{d(product.gold_weight_g)} g"
                    + (f" {product.gold_purity}k" if product.gold_purity else ""),
                    f"{d(product.stone_weight_ct)} ct" if d(product.stone_weight_ct) else None,
                    f"cost {d(product.total_cost) + d(product.material_cost)}",
                ]
                if x
            ),
            at=product.stocked_at or product.created_at,
            reference=product.serial_no,
            to=f"/products/{product.id}",
            weight_g=d(product.gold_weight_g),
            stone_ct=d(product.stone_weight_ct) or None,
            tone="good",
        )
    )

    for tr, item in (
        await db.execute(
            select(BranchTransfer, BranchTransferItem)
            .join(BranchTransferItem, BranchTransferItem.transfer_id == BranchTransfer.id)
            .where(BranchTransferItem.product_id == product.id)
            .order_by(BranchTransfer.id)
        )
    ).all():
        events.append(
            TimelineEvent(
                kind="transfer",
                title=f"Moved {tr.from_branch.name} → {tr.to_branch.name}",
                detail=tr.status.value,
                at=tr.received_at or tr.sent_at or tr.created_at,
                reference=tr.transfer_no,
                to="/transfers",
            )
        )

    for appr, item in (
        await db.execute(
            select(Approval, ApprovalItem)
            .join(ApprovalItem, ApprovalItem.approval_id == Approval.id)
            .where(ApprovalItem.product_id == product.id)
            .order_by(Approval.id)
        )
    ).all():
        events.append(
            TimelineEvent(
                kind="approval_out",
                title=f"Out on approval to {appr.customer.name if appr.customer else 'a customer'}",
                detail=f"due {appr.due_date}" if appr.due_date else None,
                at=appr.issued_at or appr.created_at,
                reference=appr.approval_no,
                to="/approvals",
                tone="warn",
            )
        )
        if item.returned_at:
            events.append(
                TimelineEvent(
                    kind="approval_back",
                    title="Came back from approval",
                    at=item.returned_at,
                    reference=appr.approval_no,
                    to="/approvals",
                    tone="good",
                )
            )

    sold_for: Decimal | None = None
    for inv, line, cname in (
        await db.execute(
            select(Invoice, InvoiceItem, Customer.name)
            .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
            .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
            .where(InvoiceItem.product_id == product.id)
            .order_by(Invoice.id)
        )
    ).all():
        amount = d(line.line_total) if line.line_total is not None else d(line.amount or 0)
        if inv.status in (InvoiceStatus.issued, InvoiceStatus.paid):
            sold_for = amount
        events.append(
            TimelineEvent(
                kind="sold",
                title=f"Sold to {cname or 'a customer'}",
                detail=f"{inv.currency.value} {amount} · {inv.status.value}",
                at=inv.issued_at or inv.created_at,
                reference=inv.invoice_no,
                to=f"/invoices/{inv.id}",
                amount=amount,
                tone="good" if inv.status is InvoiceStatus.paid else "plain",
            )
        )

    # Undated last. A leg still out has no received date, and sorting a missing
    # timestamp as the epoch would put it before the metal was bought.
    events.sort(key=lambda e: (e.at is None, e.at or datetime.min.replace(tzinfo=timezone.utc)))

    cost = d(product.total_cost) + d(product.material_cost)
    return ProductTimeline(
        product_id=product.id,
        serial_no=product.serial_no,
        name=product.name,
        status=product.status.value,
        image_url=product.image_url,
        gold_weight_g=d(product.gold_weight_g),
        gold_purity=product.gold_purity,
        gold_tunch_pct=d(product.gold_tunch_pct) if product.gold_tunch_pct else None,
        stone_weight_ct=d(product.stone_weight_ct),
        gross_weight_g=d(product.gross_weight_g) if product.gross_weight_g else None,
        total_cost=d(product.total_cost),
        material_cost=d(product.material_cost),
        gold_rate_at_cost=d(product.gold_rate_at_cost) if product.gold_rate_at_cost else None,
        sold_for=sold_for,
        margin=(sold_for - cost) if sold_for is not None else None,
        design_id=design.id if design else None,
        design_no=design.design_no if design else None,
        events=events,
    )
