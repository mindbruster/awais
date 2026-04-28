import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_password_confirm, require_perm
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.serial import next_product_serial

router = APIRouter()
read = Depends(require_perm("product:read"))
write = Depends(require_perm("product:write"))
delete = Depends(require_perm("product:delete"))

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
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
async def delete_product(product_id: int, db: DbSession) -> None:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    await db.delete(product)
    await db.commit()


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

    fname = f"product_{product_id}_{uuid.uuid4().hex}{ext}"
    fpath = UPLOAD_DIR / fname
    fpath.write_bytes(contents)

    product.image_url = f"/static/{fname}"
    await db.commit()
    await db.refresh(product)
    return product
