import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.audit import log_action
from app.services.serial import next_product_serial
from app.services.storage import StorageError, get_storage

router = APIRouter()
read = Depends(require_perm("product:read"))
write = Depends(require_perm("product:write"))
delete = Depends(require_perm("product:delete"))

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


@router.get("", response_model=list[ProductRead], dependencies=[read])
async def list_products(
    db: DbSession,
    q: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Product]:
    stmt = select(Product).order_by(Product.id.desc()).limit(limit).offset(offset)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Product.serial_no.ilike(like), Product.name.ilike(like), Product.category.ilike(like))
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_product(payload: ProductCreate, db: DbSession) -> Product:
    data = payload.model_dump()
    if not data.get("serial_no"):
        data["serial_no"] = await next_product_serial(db)
    product = Product(**data)
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

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type: {ext or 'unknown'}",
        )

    contents = await file.read()
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image exceeds 5MB limit")

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
