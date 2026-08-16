import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.product import Product, ProductStatus
from app.schemas.product import (
    GeneratedImageRead,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.services import branches, image_gen
from app.services.audit import log_action
from app.services.serial import next_product_serial
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
    product_id: int, payload: ProductUpdate, db: DbSession
) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(product, k, v)
    try:
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
